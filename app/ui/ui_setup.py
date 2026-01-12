from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
                           QComboBox, QGroupBox, QGridLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
                           QCheckBox, QTextEdit, QSizePolicy, QColorDialog, QFrame,
                           QScrollArea, QListWidget, QListWidgetItem, QSplitter, QGraphicsDropShadowEffect,
                           QHeaderView, QSlider, QTreeView, QFormLayout, QSpacerItem, QStackedWidget,
                           QToolButton, QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap, QColor, QIcon, QPainter
from PyQt6.QtMultimediaWidgets import QVideoWidget
import pyqtgraph as pyqtgraph
from PyQt6.QtGui import QStandardItemModel
from app.core.interfaces.interface_registry import InterfaceRegistry
import cv2
import os
import sys
import numpy as np

# Import the collapsible box
from app.ui.collapsible_box import CollapsibleBox
# Import timelapse utility
from app.utils.timelapse_utils import show_timelapse_dialog
# Import data flow widget
from app.ui.data_flow_widget import DataFlowWidget
# Import theme system
from app.ui.theme import (
    COLORS, SidebarTheme, ButtonStyles, ConnectionStyles,
    StatusIndicator, StatusText, GroupBoxStyles, GraphStyles,
    TableStyles, CardStyles, TabStyles, Typography,
    InputStyles, ScrollStyles, create_shadow_effect, get_status_color
)

# Import version from app module
from app import __version__

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class CameraDisplayLabel(QLabel):
    """A QLabel that scales its pixmap efficiently to fill the available space during paintEvent."""
    def __init__(self, text="No camera connected", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pixmap = None
        self.setStyleSheet("background-color: #111; color: #888; border: 1px solid #333; border-radius: 4px; font-size: 14px;")

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        # Clear internal QLabel pixmap to avoid redundant drawing
        super().setPixmap(QPixmap())
        self.update()

    def setText(self, text):
        self._pixmap = None
        super().setText(text)

    def paintEvent(self, event):
        if self._pixmap and not self._pixmap.isNull():
            painter = QPainter(self)
            # Use SmoothPixmapTransform for better quality when resizing
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            
            label_size = self.size()
            if label_size.width() <= 0 or label_size.height() <= 0:
                return
                
            pixmap_size = self._pixmap.size()
            scaled_size = pixmap_size.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio)
            
            x = (label_size.width() - scaled_size.width()) // 2
            y = (label_size.height() - scaled_size.height()) // 2
            
            painter.drawPixmap(x, y, scaled_size.width(), scaled_size.height(), self._pixmap)
        else:
            super().paintEvent(event)

class DashMetricCard(QFrame):
    """A compact card for displaying a single sensor's current value on the dashboard"""
    def __init__(self, sensor_name, unit, color="#fff", parent=None):
        super().__init__(parent)
        self.sensor_name = sensor_name
        self.unit = unit
        self.accent_color = color
        
        self.setStyleSheet(CardStyles.metric_card(color))
        self.setMinimumHeight(70) # Reverted
        self.setMaximumHeight(90) # Reverted
        self.setFixedWidth(130)   # Reduced from 150 to 130 to make cards even narrower
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8) 
        layout.setSpacing(2)
        
        # Name and trend
        name_layout = QHBoxLayout()
        self.name_label = QLabel(sensor_name)
        self.name_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 14px; font-weight: bold;")
        name_layout.addWidget(self.name_label)
        
        name_layout.addStretch()
        
        self.trend_label = QLabel("")
        self.trend_label.setStyleSheet("font-size: 14px;")
        name_layout.addWidget(self.trend_label)
        
        layout.addLayout(name_layout)
        
        # Value and unit
        value_layout = QHBoxLayout()
        value_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.value_label = QLabel("---")
        self.value_label.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 22px; font-weight: 800;")
        value_layout.addWidget(self.value_label)
        
        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 11px; margin-bottom: 4px;")
        value_layout.addWidget(self.unit_label)
        
        value_layout.addStretch()
        layout.addLayout(value_layout)
        
        # Min/Max summary
        self.stats_label = QLabel("Min: -- | Max: --")
        self.stats_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 9px;")
        layout.addWidget(self.stats_label)
        
        self.history = [] # Buffer for smoothing trend
        self.window_size = 5 # Default, will be updated from config
        self.min_val = float('inf')
        self.max_val = float('-inf')
        self._last_trend = None # State tracking for performance

    def set_window_size(self, size):
        self.window_size = max(1, size)

    def update_value(self, value):
        if value is None:
            self.value_label.setText("---")
            if self._last_trend != "None":
                self.trend_label.setText("")
                self._last_trend = "None"
            return
            
        try:
            val_float = float(value)
            if np.isnan(val_float):
                self.value_label.setText("---")
                if self._last_trend != "None":
                    self.trend_label.setText("")
                    self._last_trend = "None"
                return

            # Update history for smoothing
            self.history.append(val_float)
            if len(self.history) > self.window_size * 2:
                self.history.pop(0)
            
            # Calculate trend
            new_trend = "stable"
            if len(self.history) >= self.window_size * 2:
                recent_avg = np.mean(self.history[-self.window_size:])
                previous_avg = np.mean(self.history[-self.window_size*2:-self.window_size])
                
                if recent_avg > previous_avg + 0.0001:
                    new_trend = "up"
                elif recent_avg < previous_avg - 0.0001:
                    new_trend = "down"
            elif len(self.history) > 1:
                if val_float > self.history[-2] + 0.0001:
                    new_trend = "up"
                elif val_float < self.history[-2] - 0.0001:
                    new_trend = "down"

            # Only update style and text if trend changed
            if new_trend != self._last_trend:
                if new_trend == "up":
                    self.trend_label.setText("↑")
                    self.trend_label.setStyleSheet(f"color: {COLORS.ERROR}; font-weight: bold; font-size: 16px;")
                elif new_trend == "down":
                    self.trend_label.setText("↓")
                    self.trend_label.setStyleSheet(f"color: {COLORS.SUCCESS}; font-weight: bold; font-size: 16px;")
                else:
                    self.trend_label.setText("→")
                    self.trend_label.setStyleSheet("color: #888; font-size: 16px;")
                self._last_trend = new_trend
            
            self.value_label.setText(f"{val_float:.3f}")
            
            # Update min/max
            changed_stats = False
            if val_float < self.min_val: 
                self.min_val = val_float
                changed_stats = True
            if val_float > self.max_val: 
                self.max_val = val_float
                changed_stats = True
            
            if changed_stats:
                self.stats_label.setText(f"Min: {self.min_val:.2f} | Max: {self.max_val:.2f}")
            
        except (ValueError, TypeError):
            self.value_label.setText(str(value))

def setup_ui(self):
    """Set up the main user interface"""
    # Create a scroll area to allow clipping when window is shrunk
    # This allows the window to be smaller than the minimum size of its contents
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    # Hide vertical scrollbar but allow horizontal if needed for clipping
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.setCentralWidget(scroll_area)

    # Create central widget with dark background
    central_widget = QWidget()
    central_widget.setStyleSheet(f"background-color: {COLORS.BG_DARK};")
    scroll_area.setWidget(central_widget)
    
    main_layout = QHBoxLayout(central_widget)
    main_layout.setSpacing(12)
    main_layout.setContentsMargins(12, 0, 2, 0) # Removed top/bottom margins to allow edge-to-edge content

    # Left sidebar
    sidebar = QWidget()
    sidebar.setFixedWidth(SidebarTheme.WIDTH)
    self.sidebar = sidebar
    
    # Note: Shadow effect removed to prevent layout jitter on hover
    # The sidebar gradient provides enough visual separation
    
    # Apply sidebar theme
    sidebar.setStyleSheet(SidebarTheme.CONTAINER)
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setSpacing(2)
    sidebar_layout.setContentsMargins(0, 10, 0, 20)

    # Sidebar toggle button
    self.sidebar_collapsed = True  # Start collapsed by default for more space
    toggle_container = QHBoxLayout()
    toggle_container.setContentsMargins(5, 5, 10, 5)
    toggle_container.addStretch()
    self.sidebar_toggle_btn = QPushButton("«")
    self.sidebar_toggle_btn.setFixedSize(30, 30)
    self.sidebar_toggle_btn.setToolTip("Collapse Sidebar")
    self.sidebar_toggle_btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {COLORS.TEXT_SECONDARY};
            border: 1px solid {COLORS.BORDER_DEFAULT};
            border-radius: 15px;
            font-size: 16px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background: {COLORS.BG_ELEVATED};
            color: {COLORS.TEXT_PRIMARY};
            border-color: {COLORS.PRIMARY};
        }}
    """)
    toggle_container.addWidget(self.sidebar_toggle_btn)
    sidebar_layout.addLayout(toggle_container)

    # Compact label for collapsed state (shows "A" for Artefakt)
    self.collapsed_title_label = QLabel("A")
    self.collapsed_title_label.setStyleSheet(f"""
        QLabel {{
            color: {COLORS.TEXT_PRIMARY};
            font-size: 24px;
            font-weight: bold;
            background: transparent;
            padding: 8px 0px;
        }}
    """)
    self.collapsed_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.collapsed_title_label.setVisible(False)  # Hidden by default (expanded state)
    sidebar_layout.addWidget(self.collapsed_title_label)

    # Program name (Artefakt)
    self.program_name_text = QLabel("Artefakt")
    self.program_name_text.setStyleSheet(SidebarTheme.TITLE)
    self.program_name_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sidebar_layout.addWidget(self.program_name_text)
    
    # Version text without logo
    self.version_text = QLabel(f"DAQ <span style='font-size: 12px;'>v{__version__}</span>")
    self.version_text.setStyleSheet(SidebarTheme.VERSION)
    self.version_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sidebar_layout.addWidget(self.version_text)
    
    # Add vertical spacing after the version text - reduced
    self.sidebar_v_spacer1 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    sidebar_layout.addItem(self.sidebar_v_spacer1)
    
    # Add separator
    self.sidebar_separator1 = QFrame()
    self.sidebar_separator1.setFrameShape(QFrame.Shape.HLine)
    self.sidebar_separator1.setStyleSheet(SidebarTheme.SEPARATOR)
    sidebar_layout.addWidget(self.sidebar_separator1)
    
    # Project status section - compact, no visible box
    self.project_status_container = QWidget()
    self.project_status_container.setStyleSheet(SidebarTheme.STATUS_CONTAINER)
    project_status_layout = QVBoxLayout(self.project_status_container)
    project_status_layout.setContentsMargins(5, 0, 5, 0)
    project_status_layout.setSpacing(1)
    
    # Project status label - removed as requested
    
    # Common style for labels (fixed width for alignment)
    label_style = "color: rgba(255, 255, 255, 0.5); font-size: 11px; background: transparent;"
    value_style_green = f"color: {COLORS.SUCCESS}; font-size: 11px; background: transparent;"
    value_style_warning = f"color: {COLORS.WARNING}; font-size: 11px; background: transparent;"
    label_width = 100  # Fixed width for alignment (more space for labels)
    
    # Project name
    project_name_layout = QHBoxLayout()
    project_name_layout.setSpacing(4)
    project_label = QLabel("Project:")
    project_label.setFixedWidth(label_width)
    project_label.setStyleSheet(label_style)
    project_name_layout.addWidget(project_label)
    self.sidebar_project_name = QLabel("None")
    self.sidebar_project_name.setStyleSheet(value_style_green)
    project_name_layout.addWidget(self.sidebar_project_name, 1)
    project_status_layout.addLayout(project_name_layout)
    
    # Test series name
    test_series_layout = QHBoxLayout()
    test_series_layout.setSpacing(4)
    series_label = QLabel("Test Series:")
    series_label.setFixedWidth(label_width)
    series_label.setStyleSheet(label_style)
    test_series_layout.addWidget(series_label)
    self.sidebar_test_series = QLabel("None")
    self.sidebar_test_series.setStyleSheet(value_style_green)
    test_series_layout.addWidget(self.sidebar_test_series, 1)
    project_status_layout.addLayout(test_series_layout)
    
    # Ready status
    ready_layout = QHBoxLayout()
    ready_layout.setSpacing(4)
    ready_label = QLabel("Run Status:")
    ready_label.setFixedWidth(label_width)
    ready_label.setStyleSheet(label_style)
    ready_layout.addWidget(ready_label)
    self.sidebar_ready_status = QLabel("Not Ready")
    self.sidebar_ready_status.setStyleSheet(value_style_warning)
    ready_layout.addWidget(self.sidebar_ready_status, 1)
    project_status_layout.addLayout(ready_layout)
    
    sidebar_layout.addWidget(self.project_status_container)
    
    # Add separator
    self.sidebar_separator2 = QFrame()
    self.sidebar_separator2.setFrameShape(QFrame.Shape.HLine)
    self.sidebar_separator2.setStyleSheet(SidebarTheme.SEPARATOR)
    sidebar_layout.addWidget(self.sidebar_separator2)
    
    # Navigation buttons with SVG icons instead of emoji
    nav_buttons = [
        "Projects",
        "Settings",
        "Camera",
        "Sensors",
        "Automation",
        "Dashboard",
        "Graphs",
        "Notes"  # Add Notes button after Graphs
    ]

    # Create button group for exclusive selection
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import QSize
    from PyQt6.QtWidgets import QToolButton

    # Use navigation button style from theme
    tool_button_style = SidebarTheme.NAV_BUTTON

    # Nav buttons fixed height - slightly increased to prevent text clipping
    nav_btn_height = 70 
    
    self.nav_buttons = []
    for button_name in nav_buttons:
        # Create a tool button with icon on top and text below
        btn = QToolButton()
        btn.setStyleSheet(tool_button_style)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setText(button_name)
        
        if button_name == "Dashboard":
            btn.setToolTip("This graph shows all active sensors that are enabled in the Sensors tab with 'Show in Graph' checked.")
        
        # Load SVG icon and set it
        svg_path = resource_path(f"app/ui/{button_name}.svg")
        btn.setIcon(QIcon(svg_path))
        btn.setIconSize(QSize(28, 28)) # Slightly smaller icon
        
        # Set the tool button style to text under icon
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        
        # Fixed size to prevent layout recalculation on hover
        btn.setFixedHeight(nav_btn_height)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Add spacing between specific buttons - reduced
        if button_name == "Projects" or button_name == "Settings":
            sidebar_layout.addWidget(btn)
            # Add spacer after Projects (and before Camera)
            if button_name == "Projects":
                spacer = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                sidebar_layout.addItem(spacer)
        elif button_name == "Automation":
            sidebar_layout.addWidget(btn)
            # Add spacer after Automation (and before Dashboard)
            spacer = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            sidebar_layout.addItem(spacer)
        else:
            sidebar_layout.addWidget(btn)
            
        self.nav_buttons.append(btn)
        if button_name == "Projects":
            btn.setChecked(True)
        
        # Make the Settings button invisible
        if button_name == "Settings":
            btn.setVisible(False)

    sidebar_layout.addStretch()

    # Add Start/Stop buttons at the bottom
    control_buttons = QHBoxLayout()
    control_buttons.setContentsMargins(10, 10, 10, 10)
    control_buttons.setSpacing(10)

    self.toggle_btn = QPushButton("Start")
    
    # Style for toggle button - using theme system
    self.start_btn_style = ButtonStyles.success()
    self.stop_btn_style = ButtonStyles.danger()
    
    # Set initial style (start)
    self.toggle_btn.setStyleSheet(self.start_btn_style)

    # Create blink timer for the "Running..." text
    self.blink_timer = QTimer()
    self.blink_timer.setInterval(1000)  # 1Hz
    self.blink_visible = True
    self.blink_timer.timeout.connect(self.update_running_text)
    
    # Connect toggle button
    self.toggle_btn.clicked.connect(self.on_toggle_clicked)

    control_buttons.addWidget(self.toggle_btn)
    sidebar_layout.addLayout(control_buttons)
    
    # Add logo image below toggle button
    self.logo_label = QLabel()
    self.full_logo_pixmap = None
    self.small_icon_pixmap = None
    
    try:
        # Load full logo
        logo_paths = [
            resource_path("assets/Evo-Labs_logo.png"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "Evo-Labs_logo.png"),
            "assets/Evo-Labs_logo.png"
        ]
        for path in logo_paths:
            if os.path.exists(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    self.full_logo_pixmap = pix.scaled(140, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    break
        
        # Load small icon
        icon_paths = [
            resource_path("assets/Evo-Labs_ICON.ico"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "Evo-Labs_ICON.ico"),
            "assets/Evo-Labs_ICON.ico"
        ]
        for path in icon_paths:
            if os.path.exists(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    self.small_icon_pixmap = pix.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    break
                    
        if self.full_logo_pixmap:
            self.logo_label.setPixmap(self.full_logo_pixmap)
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.logo_label.setStyleSheet("background: transparent;")
            sidebar_layout.addWidget(self.logo_label)
    except Exception as e:
        pass

    # Sidebar toggle logic
    def toggle_sidebar():
        self.sidebar_collapsed = not self.sidebar_collapsed
        
        if self.sidebar_collapsed:
            self.sidebar.setFixedWidth(SidebarTheme.COLLAPSED_WIDTH)
            self.sidebar_toggle_btn.setText("»")
            self.sidebar_toggle_btn.setToolTip("Expand Sidebar")
            self.program_name_text.setVisible(False)
            self.version_text.setVisible(False)
            self.sidebar_separator1.setVisible(False)
            self.project_status_container.setVisible(False)
            self.sidebar_separator2.setVisible(False)
            self.collapsed_title_label.setVisible(True)  # Show compact label when collapsed
            
            # Switch to small icon
            if self.small_icon_pixmap:
                self.logo_label.setPixmap(self.small_icon_pixmap)
                self.logo_label.setVisible(True)
            else:
                self.logo_label.setVisible(False)
            
            # Update nav buttons
            for btn in self.nav_buttons:
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                # Adjust size for collapsed mode
                btn.setFixedWidth(SidebarTheme.COLLAPSED_WIDTH - 10)
                btn.setToolTip(btn.text()) # Ensure text is available as tooltip
            
            # Update start/stop button
            self.toggle_btn.setToolTip(self.toggle_btn.text())
            if self.toggle_btn.text() == "Start":
                self.toggle_btn.setText("▶")
            else:
                self.toggle_btn.setText("■")
            self.toggle_btn.setFixedWidth(SidebarTheme.COLLAPSED_WIDTH - 20)
            # Reduce padding for collapsed mode
            self.toggle_btn.setStyleSheet(self.toggle_btn.styleSheet() + "QPushButton { padding: 12px 2px; }")
            
        else:
            self.sidebar.setFixedWidth(SidebarTheme.WIDTH)
            self.sidebar_toggle_btn.setText("«")
            self.sidebar_toggle_btn.setToolTip("Collapse Sidebar")
            self.program_name_text.setVisible(True)
            self.version_text.setVisible(True)
            self.sidebar_separator1.setVisible(True)
            self.project_status_container.setVisible(True)
            self.sidebar_separator2.setVisible(True)
            self.collapsed_title_label.setVisible(False)  # Hide compact label when expanded
            
            # Switch to full logo
            if self.full_logo_pixmap:
                self.logo_label.setPixmap(self.full_logo_pixmap)
                self.logo_label.setVisible(True)
            else:
                self.logo_label.setVisible(False)
            
            # Update nav buttons
            for btn in self.nav_buttons:
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                btn.setMinimumWidth(0) # Reset
                btn.setMaximumWidth(16777215) # QWIDGETSIZE_MAX
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            
            # Update start/stop button
            if self.toggle_btn.text() == "▶":
                self.toggle_btn.setText("Start")
            elif self.toggle_btn.text() == "■":
                self.toggle_btn.setText("Stop")
            self.toggle_btn.setMinimumWidth(0)
            self.toggle_btn.setMaximumWidth(16777215)
            self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # Reset padding by reapplying original style
            if self.running:
                self.toggle_btn.setStyleSheet(self.stop_btn_style)
            else:
                self.toggle_btn.setStyleSheet(self.start_btn_style)

    self.sidebar_toggle_btn.clicked.connect(toggle_sidebar)
    self.toggle_sidebar_func = toggle_sidebar # Store for later use if needed

    # Main content area
    content_area = QWidget()
    content_layout = QHBoxLayout(content_area)
    content_layout.setSpacing(10)
    content_layout.setContentsMargins(10, 0, 2, 0) # Removed top/bottom margins to allow edge-to-edge content

    # Create stacked widget
    self.stacked_widget = QStackedWidget()
    # Flatten stacked widget to remove any internal padding/margins
    self.stacked_widget.setStyleSheet("QStackedWidget { padding: 0px; margin: 0px; border: none; }")

    # Dashboard tab
    dashboard_tab = QWidget()
    self.dashboard_tab = dashboard_tab
    dashboard_layout = QVBoxLayout(dashboard_tab)
    # Reduced top/bottom margins to 0 to maximize space for dashboard content
    dashboard_layout.setContentsMargins(10, 0, 2, 0) 
    dashboard_layout.setSpacing(10)

    # --- NEW: Dashboard Header (Status & Project Info) ---
    header_frame = QFrame()
    header_frame.setStyleSheet(f"background-color: {COLORS.BG_CARD}; border-radius: 8px; border: 1px solid {COLORS.BORDER_DEFAULT};")
    header_frame.setFixedHeight(50) # Reduced from 60
    header_layout = QHBoxLayout(header_frame)
    header_layout.setContentsMargins(15, 0, 15, 0)

    # Status Indicators Group
    status_layout = QHBoxLayout()
    status_layout.setSpacing(8) # Reduced from 15
    
    def create_status_indicator(label_text):
        container = QHBoxLayout()
        container.setSpacing(4) # Tighter spacing
        led = QFrame()
        led.setFixedSize(10, 10) # Slightly smaller LED
        led.setStyleSheet(StatusIndicator.inactive(10))
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        container.addWidget(led)
        container.addWidget(lbl)
        return container, led

    self.status_indicators = {}
    
    # DAQ HW Status
    daq_cont, self.led_daq = create_status_indicator("DAQ HW")
    tooltip_daq = "Status of Hardware Data Acquisition (Green=Active, Red=Error)"
    daq_cont.itemAt(0).widget().setToolTip(tooltip_daq) # LED
    daq_cont.itemAt(1).widget().setToolTip(tooltip_daq) # Text
    status_layout.addLayout(daq_cont)
    
    # Recording Status
    rec_cont, self.led_recording = create_status_indicator("RECORDING")
    tooltip_rec = "Data Recording Status (Green=Recording, Gray=Idle)"
    rec_cont.itemAt(0).widget().setToolTip(tooltip_rec) # LED
    rec_cont.itemAt(1).widget().setToolTip(tooltip_rec) # Text
    status_layout.addLayout(rec_cont)
    
    # Automation Status
    auto_cont, self.led_automation = create_status_indicator("AUTO")
    tooltip_auto = "Automation Sequence Status (Green=Running, Gray=Idle)"
    auto_cont.itemAt(0).widget().setToolTip(tooltip_auto) # LED
    auto_cont.itemAt(1).widget().setToolTip(tooltip_auto) # Text
    status_layout.addLayout(auto_cont)
    
    header_layout.addLayout(status_layout)
    header_layout.addSpacing(10) # Reduced from 15
    
    # Project Summary info
    project_info_layout = QHBoxLayout()
    project_info_layout.setSpacing(8) # Reduced from 12
    
    def create_info_item(label, value_placeholder):
        layout = QVBoxLayout()
        layout.setSpacing(0)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 9px; text-transform: uppercase;")
        val = QLabel(value_placeholder)
        val.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
        layout.addWidget(lbl)
        layout.addWidget(val)
        return layout, val

    pi_layout, self.dash_project_val = create_info_item("Project", "---")
    project_info_layout.addLayout(pi_layout)
    
    ts_layout, self.dash_series_val = create_info_item("Series", "---")
    project_info_layout.addLayout(ts_layout)
    
    rn_layout, self.dash_run_val = create_info_item("Current Run", "---")
    project_info_layout.addLayout(rn_layout)
    
    dur_layout, self.dash_duration_val = create_info_item("Duration", "00:00:00")
    project_info_layout.addLayout(dur_layout)
    
    # Timespan control - formatted like duration (label above, combobox below)
    timespan_layout = QVBoxLayout()
    timespan_layout.setSpacing(0)
    timespan_label = QLabel("Timespan")
    timespan_label.setStyleSheet(f"color: {COLORS.TEXT_MUTED}; font-size: 10px; text-transform: uppercase;")
    timespan_layout.addWidget(timespan_label)
    self.dashboard_timespan = QComboBox()
    self.dashboard_timespan.addItems(["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"])
    self.dashboard_timespan.setCurrentText("All")
    self.dashboard_timespan.setMinimumWidth(60) # Reduced from 80
    self.dashboard_timespan.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
    timespan_layout.addWidget(self.dashboard_timespan)
    project_info_layout.addLayout(timespan_layout)
    
    header_layout.addLayout(project_info_layout)
    header_layout.addSpacing(10) # Reduced from 20
    
    # Display Options Checkboxes (arranged in two rows)
    display_options_layout = QVBoxLayout()
    display_options_layout.setSpacing(2) # Reduced from 5
    display_options_layout.setContentsMargins(0, 0, 0, 0)
    
    # First row
    first_row = QHBoxLayout()
    first_row.setSpacing(10) # Reduced from 15
    first_row.setContentsMargins(0, 0, 0, 0)
    
    self.checkbox_automation_status = QCheckBox("Auto Status") # Shortened
    self.checkbox_automation_status.setChecked(True)
    self.checkbox_automation_status.setStyleSheet(f"""
        QCheckBox {{
            color: {COLORS.TEXT_SECONDARY};
            font-size: 10px;
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
        }}
    """)
    first_row.addWidget(self.checkbox_automation_status)
    
    self.checkbox_recent_events = QCheckBox("Events") # Shortened
    self.checkbox_recent_events.setChecked(True)
    self.checkbox_recent_events.setStyleSheet(f"""
        QCheckBox {{
            color: {COLORS.TEXT_SECONDARY};
            font-size: 10px;
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
        }}
    """)
    first_row.addWidget(self.checkbox_recent_events)
    
    display_options_layout.addLayout(first_row)
    
    # Second row
    second_row = QHBoxLayout()
    second_row.setSpacing(10) # Reduced from 15
    second_row.setContentsMargins(0, 0, 0, 0)
    
    self.checkbox_image = QCheckBox("Image")
    self.checkbox_image.setChecked(True)
    self.checkbox_image.setStyleSheet(f"""
        QCheckBox {{
            color: {COLORS.TEXT_SECONDARY};
            font-size: 10px;
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
        }}
    """)
    # Set maximum width to constrain the checkbox text space and ensure proper alignment
    self.checkbox_image.setMaximumWidth(60)
    second_row.addWidget(self.checkbox_image)
    
    self.checkbox_camera_preview = QCheckBox("Camera") # Renamed from "Preview"
    self.checkbox_camera_preview.setChecked(True)
    self.checkbox_camera_preview.setStyleSheet(f"""
        QCheckBox {{
            color: {COLORS.TEXT_SECONDARY};
            font-size: 10px;
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
        }}
    """)
    second_row.addWidget(self.checkbox_camera_preview)
    
    display_options_layout.addLayout(second_row)
    
    # Helper function to adjust splitter when boxes are shown/hidden
    def adjust_splitter_for_visibility():
        if not hasattr(self, 'dashboard_splitter') or not hasattr(self, 'lower_widget'):
            return
        
        # Check if any checkbox is checked (this tells us if boxes should be visible)
        boxes_should_be_visible = (
            (hasattr(self, 'checkbox_automation_status') and self.checkbox_automation_status.isChecked()) or
            (hasattr(self, 'checkbox_recent_events') and self.checkbox_recent_events.isChecked()) or
            (hasattr(self, 'checkbox_image') and self.checkbox_image.isChecked()) or
            (hasattr(self, 'checkbox_camera_preview') and self.checkbox_camera_preview.isChecked())
        )
        
        # If no boxes should be visible, hide the lower widget and expand the upper part
        if not boxes_should_be_visible:
            self.lower_widget.setVisible(False)
            # Get current total height and give it all to the upper part
            current_sizes = self.dashboard_splitter.sizes()
            if len(current_sizes) == 2:
                total_height = sum(current_sizes) if sum(current_sizes) > 0 else self.dashboard_splitter.height()
                if total_height > 0:
                    self.dashboard_splitter.setSizes([total_height, 0])
        else:
            # At least one box should be visible, show the lower widget
            self.lower_widget.setVisible(True)
            # Restore reasonable splitter sizes
            current_sizes = self.dashboard_splitter.sizes()
            if len(current_sizes) == 2:
                # If lower part is collapsed (size 0), restore default sizes
                if current_sizes[1] == 0:
                    total_height = current_sizes[0] if current_sizes[0] > 0 else self.dashboard_splitter.height()
                    if total_height > 0:
                        self.dashboard_splitter.setSizes([int(total_height * 0.6), int(total_height * 0.4)])
    
    # Toggle functions for display options
    def toggle_automation_status_display(checked):
        if hasattr(self, 'dashboard_automation_group'):
            self.dashboard_automation_group.setVisible(checked)
        adjust_splitter_for_visibility()
    
    def toggle_recent_events_display(checked):
        if hasattr(self, 'events_group'):
            self.events_group.setVisible(checked)
        adjust_splitter_for_visibility()
    
    def toggle_image_display(checked):
        if hasattr(self, 'dashboard_snapshot_group'):
            self.dashboard_snapshot_group.setVisible(checked)
        adjust_splitter_for_visibility()
    
    def toggle_camera_preview_display(checked):
        if hasattr(self, 'dashboard_camera_group'):
            self.dashboard_camera_group.setVisible(checked)
        adjust_splitter_for_visibility()
    
    # Connect checkboxes to toggle functions
    self.checkbox_automation_status.toggled.connect(toggle_automation_status_display)
    self.checkbox_recent_events.toggled.connect(toggle_recent_events_display)
    self.checkbox_image.toggled.connect(toggle_image_display)
    self.checkbox_camera_preview.toggled.connect(toggle_camera_preview_display)
    
    header_layout.addLayout(display_options_layout)
    header_layout.addStretch()
    
    # Quick Action Buttons in Header
    header_actions = QHBoxLayout()
    header_actions.setSpacing(8)
    
    self.dash_snapshot_btn = QPushButton()
    self.dash_snapshot_btn.setToolTip("Take Snapshot")
    self.dash_snapshot_btn.setStyleSheet(ButtonStyles.secondary("small"))
    self.dash_snapshot_btn.setFixedSize(36, 36)
    self.dash_snapshot_btn.setIcon(QIcon(resource_path("app/ui/Camera.svg")))
    self.dash_snapshot_btn.setIconSize(QSize(22, 22))
    header_actions.addWidget(self.dash_snapshot_btn)
    
    self.dash_note_btn = QPushButton()
    self.dash_note_btn.setToolTip("Quick Note")
    self.dash_note_btn.setStyleSheet(ButtonStyles.secondary("small"))
    self.dash_note_btn.setFixedSize(36, 36)
    self.dash_note_btn.setIcon(QIcon(resource_path("app/ui/Notes.svg")))
    self.dash_note_btn.setIconSize(QSize(22, 22))
    header_actions.addWidget(self.dash_note_btn)
    
    self.dash_settings_btn = QPushButton()
    self.dash_settings_btn.setToolTip("Dashboard Settings")
    self.dash_settings_btn.setStyleSheet(ButtonStyles.secondary("small"))
    self.dash_settings_btn.setFixedSize(36, 36)
    self.dash_settings_btn.setIcon(QIcon(resource_path("app/ui/Settings.svg")))
    self.dash_settings_btn.setIconSize(QSize(22, 22))
    header_actions.addWidget(self.dash_settings_btn)
    
    header_layout.addLayout(header_actions)
    
    dashboard_layout.addWidget(header_frame)
    
    # Main content splitter
    self.dashboard_splitter = QSplitter(Qt.Orientation.Vertical)
    self.dashboard_splitter.setChildrenCollapsible(True) # Allow sliding to hide sections entirely
    self.dashboard_splitter.setStyleSheet(f"""
        QSplitter::handle {{
            background-color: {COLORS.BORDER_DEFAULT};
        }}
        QSplitter::handle:hover {{
            background-color: {COLORS.PRIMARY};
        }}
    """)
    
    # Upper Part: Metrics + Graph (Horizontal Splitter)
    upper_splitter = QSplitter(Qt.Orientation.Horizontal)
    upper_splitter.setChildrenCollapsible(True) # Allow sections to be collapsed completely (hiding metrics)
    upper_splitter.setStyleSheet(f"""
        QSplitter::handle {{
            background-color: {COLORS.BORDER_DEFAULT};
            width: 2px;
        }}
        QSplitter::handle:hover {{
            background-color: {COLORS.PRIMARY};
        }}
    """)
    
    # Left side: Live Metrics Grid
    metrics_group = QGroupBox("Live Metrics")
    metrics_group.setStyleSheet(GroupBoxStyles.tight())
    metrics_group.setMinimumWidth(200)
    metrics_layout = QVBoxLayout(metrics_group)
    
    self.metrics_scroll = QScrollArea()
    self.metrics_scroll.setWidgetResizable(True)
    self.metrics_scroll.setStyleSheet("background: transparent; border: none;")
    self.metrics_container = QWidget()
    self.metrics_container.setStyleSheet("background: transparent;")
    self.metrics_grid = QGridLayout(self.metrics_container)
    self.metrics_grid.setContentsMargins(0, 0, 0, 0)
    self.metrics_grid.setSpacing(8)
    self.metrics_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
    
    self.metrics_scroll.setWidget(self.metrics_container)
    metrics_layout.addWidget(self.metrics_scroll)
    
    # Add an event filter to the container to handle responsive column layout
    self.metrics_container.installEventFilter(self)
    
    upper_splitter.addWidget(metrics_group)
    
    # Right side: Graph Area
    graph_container_widget = QWidget()
    graph_container_layout = QVBoxLayout(graph_container_widget)
    graph_container_layout.setContentsMargins(0, 0, 0, 0)
    
    # Dashboard graph widget (Existing logic but wrapped)
    dashboard_graph_group = QGroupBox("Sensor Overview")
    dashboard_graph_group.setStyleSheet(GroupBoxStyles.tight())
    dashboard_graph_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    
    dashboard_graph_container = QHBoxLayout(dashboard_graph_group)
    
    self.dashboard_graph_widget = pyqtgraph.PlotWidget()
    GraphStyles.apply_dark_theme(self.dashboard_graph_widget)
    self.dashboard_graph_widget.setLabel('left', 'Value')
    self.dashboard_graph_widget.setLabel('bottom', 'Sample Count')
    dashboard_graph_container.addWidget(self.dashboard_graph_widget, 1)
    
    graph_container_layout.addWidget(dashboard_graph_group, 1)
    
    # Replay controls (Existing)
    replay_controls = QWidget()
    replay_controls_layout = QHBoxLayout(replay_controls)
    replay_controls_layout.setContentsMargins(0, 2, 0, 2)
    replay_controls_layout.setSpacing(8)
    
    self.replay_play_btn = QPushButton("Play")
    self.replay_play_btn.setCheckable(True)
    self.replay_speed = QComboBox()
    self.replay_speed.addItems(["0.25x", "0.5x", "1x", "2x", "4x"])
    self.replay_speed.setCurrentText("1x")
    self.replay_time_label = QLabel("00:00.0 / 00:00.0")
    self.replay_coarse = QSlider(Qt.Orientation.Horizontal)
    self.replay_coarse.setRange(0, 1000)
    
    replay_controls_layout.addWidget(QLabel("Replay:"))
    replay_controls_layout.addWidget(self.replay_play_btn)
    replay_controls_layout.addWidget(QLabel("Speed"))
    replay_controls_layout.addWidget(self.replay_speed)
    replay_controls_layout.addWidget(self.replay_time_label)
    replay_controls_layout.addWidget(QLabel("Position"))
    replay_controls_layout.addWidget(self.replay_coarse, 1)
    
    graph_container_layout.addWidget(replay_controls)
    
    upper_splitter.addWidget(graph_container_widget)
    
    # Set initial sizes for the horizontal splitter (e.g., 20% metrics, 80% graph)
    upper_splitter.setSizes([280, 1000])
    
    self.dashboard_splitter.addWidget(upper_splitter)
    
    # Lower part - Automation Status and Camera Preview with Splitter
    self.lower_widget = QWidget()
    # Use QVBoxLayout for the main lower widget container
    lower_layout = QVBoxLayout(self.lower_widget) 
    lower_layout.setContentsMargins(0, 0, 0, 0)
    
    # Create a horizontal splitter for the two panels
    lower_splitter = QSplitter(Qt.Orientation.Horizontal)
    lower_splitter.setChildrenCollapsible(False)

    # Automation Status panel (Left side)
    self.dashboard_automation_group = QGroupBox("Automation Status")
    self.dashboard_automation_group.setStyleSheet(GroupBoxStyles.default())
    dashboard_automation_layout = QVBoxLayout(self.dashboard_automation_group)

    # --- ADDED --- New table for detailed status
    self.dashboard_automation_table = QTableWidget()
    self.dashboard_automation_table.setMinimumHeight(80) # Reduced from default
    self.dashboard_automation_table.setColumnCount(5)
    self.dashboard_automation_table.setHorizontalHeaderLabels(["Sequence", "Status", "Current Step", "Next Step", "Time/Trigger"])
    # Allow columns to resize, make Sequence name stretch
    header = self.dashboard_automation_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Sequence name initially stretches
    self.dashboard_automation_table.verticalHeader().setVisible(False) # Hide row numbers
    self.dashboard_automation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    self.dashboard_automation_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    self.dashboard_automation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Make read-only
    self.dashboard_automation_table.setAlternatingRowColors(True)
    dashboard_automation_layout.addWidget(self.dashboard_automation_table)

    self.dashboard_automation_group.setMinimumWidth(200) # Reduced from 350 to allow better window shrinking

    # Add automation group to the splitter
    lower_splitter.addWidget(self.dashboard_automation_group)

    # --- NEW: Events Log in the middle ---
    self.events_group = QGroupBox("Recent System Events")
    self.events_group.setStyleSheet(GroupBoxStyles.default())
    events_group_layout = QVBoxLayout(self.events_group)
    
    self.dash_events_list = QListWidget()
    self.dash_events_list.setStyleSheet(f"""
        QListWidget {{
            background-color: {COLORS.BG_DARK};
            border: none;
            color: {COLORS.TEXT_SECONDARY};
            font-size: 10px;
        }}
    """)
    events_group_layout.addWidget(self.dash_events_list)
    lower_splitter.addWidget(self.events_group)

    # --- NEW: Last Images Box ---
    self.dashboard_snapshot_group = QGroupBox("Last Images")
    self.dashboard_snapshot_group.setStyleSheet(GroupBoxStyles.default())
    dashboard_snapshot_layout = QVBoxLayout(self.dashboard_snapshot_group)
    
    self.dashboard_snapshot_label = QLabel("No image available")
    self.dashboard_snapshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.dashboard_snapshot_label.setStyleSheet(f"background-color: #222; color: {COLORS.TEXT_SECONDARY}; border: 1px solid {COLORS.BORDER_DEFAULT};")
    # Small minimum size so it doesn't block layout shrinking
    self.dashboard_snapshot_label.setMinimumSize(50, 50) # Reduced from 80, 80
    # Use Ignored policy so the label's size hint (from the pixmap) doesn't force the layout to expand.
    # The label will instead take the space provided by the layout.
    self.dashboard_snapshot_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
    # We will scale the pixmap manually in main_window.py to maintain aspect ratio
    self.dashboard_snapshot_label.setScaledContents(False)
    dashboard_snapshot_layout.addWidget(self.dashboard_snapshot_label)
    
    # Navigation buttons for snapshots
    snapshot_nav_layout = QHBoxLayout()
    self.snapshot_back_btn = QPushButton("◀ Back")
    self.snapshot_view_btn = QPushButton("👁 View")
    self.snapshot_next_btn = QPushButton("Next ▶")
    
    self.snapshot_back_btn.setStyleSheet(ButtonStyles.secondary("small"))
    self.snapshot_view_btn.setStyleSheet(ButtonStyles.secondary("small"))
    self.snapshot_next_btn.setStyleSheet(ButtonStyles.secondary("small"))
    
    self.snapshot_back_btn.setToolTip("Previous Image")
    self.snapshot_view_btn.setToolTip("View Full Size")
    self.snapshot_next_btn.setToolTip("Next Image")
    
    snapshot_nav_layout.addWidget(self.snapshot_back_btn)
    snapshot_nav_layout.addWidget(self.snapshot_view_btn)
    snapshot_nav_layout.addWidget(self.snapshot_next_btn)
    dashboard_snapshot_layout.addLayout(snapshot_nav_layout)
    
    lower_splitter.addWidget(self.dashboard_snapshot_group)

    # Camera preview group box (Right side)
    self.dashboard_camera_group = QGroupBox("Camera") # Renamed from "Camera Preview"
    self.dashboard_camera_group.setStyleSheet(GroupBoxStyles.default())
    dashboard_camera_layout = QVBoxLayout(self.dashboard_camera_group)
    
    # Camera source selection (4 checkboxes)
    camera_source_layout = QHBoxLayout()
    camera_source_layout.setSpacing(12)
    
    self.dashboard_camera_checkboxes = []
    for i in range(4):
        cb = QCheckBox(f"Cam {i+1}")
        cb.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
        # Connect with slot index
        cb.toggled.connect(
            lambda _, idx=i: self.switch_dashboard_camera_source(idx) if hasattr(self, 'switch_dashboard_camera_source') else None
        )
        self.dashboard_camera_checkboxes.append(cb)
        camera_source_layout.addWidget(cb)

    # Dashboard video audio controls
    camera_source_layout.addSpacing(8)
    self.dashboard_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.dashboard_volume_slider.setRange(0, 100)
    self.dashboard_volume_slider.setValue(100)
    self.dashboard_volume_slider.setFixedWidth(80)
    self.dashboard_volume_slider.setEnabled(True)
    camera_source_layout.addWidget(self.dashboard_volume_slider)
    self.dashboard_mute_checkbox = QCheckBox("🔇")
    self.dashboard_mute_checkbox.setToolTip("Mute")
    self.dashboard_mute_checkbox.setEnabled(True)
    camera_source_layout.addWidget(self.dashboard_mute_checkbox)
    
    camera_source_layout.addStretch()
    dashboard_camera_layout.addLayout(camera_source_layout)
    
    # Placeholder for when no cameras are selected
    self.dashboard_camera_placeholder = CameraDisplayLabel("No camera selected")
    self.dashboard_camera_placeholder.setStyleSheet("background-color: #111; color: #888; border: 1px solid #333; border-radius: 4px; font-size: 14px;")
    self.dashboard_camera_placeholder.setMinimumHeight(80)
    self.dashboard_camera_placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    dashboard_camera_layout.addWidget(self.dashboard_camera_placeholder)
    
    # Camera preview labels (4-slot Dynamic Layout)
    self.dashboard_camera_rows_layout = QVBoxLayout()
    self.dashboard_camera_rows_layout.setSpacing(4)
    self.dashboard_camera_rows_layout.setContentsMargins(0, 0, 0, 0)
    
    self.dashboard_camera_row_widgets = []
    self.dashboard_camera_row_layouts = []
    
    self.dashboard_camera_labels = []
    for row in range(2):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setSpacing(4)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard_camera_row_widgets.append(row_widget)
        self.dashboard_camera_row_layouts.append(row_layout)
        self.dashboard_camera_rows_layout.addWidget(row_widget)
        
        for col in range(2):
            lbl = CameraDisplayLabel("No camera connected")
            lbl.setMinimumHeight(80)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.dashboard_camera_labels.append(lbl)
            row_layout.addWidget(lbl)
            
            # Start hidden so placeholder shows
            lbl.hide()
        
        # Start hidden
        row_widget.hide()

    # Compatibility attributes
    self.dashboard_camera_label_1 = self.dashboard_camera_labels[0]
    self.dashboard_camera_label_2 = self.dashboard_camera_labels[1]
    self.dashboard_camera_label_3 = self.dashboard_camera_labels[2]
    self.dashboard_camera_label_4 = self.dashboard_camera_labels[3]
    self.dashboard_camera_label = self.dashboard_camera_label_1
    
    dashboard_camera_layout.addLayout(self.dashboard_camera_rows_layout)

    # Video playback widgets for review mode (4-slot Dynamic Layout)
    self.dashboard_video_rows_layout = QVBoxLayout()
    self.dashboard_video_rows_layout.setSpacing(4)
    self.dashboard_video_rows_layout.setContentsMargins(0, 0, 0, 0)
    
    self.dashboard_video_row_widgets = []
    
    self.dashboard_video_widgets = []
    for row in range(2):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setSpacing(4)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard_video_row_widgets.append(row_widget)
        self.dashboard_video_rows_layout.addWidget(row_widget)
        
        for col in range(2):
            vw = QVideoWidget()
            vw.setMinimumHeight(80)
            vw.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            vw.hide()
            self.dashboard_video_widgets.append(vw)
            row_layout.addWidget(vw, 1)
        
        row_widget.hide()
    
    self.dashboard_video_widget = self.dashboard_video_widgets[0] # Compatibility
    dashboard_camera_layout.addLayout(self.dashboard_video_rows_layout)
    
    # Add camera group to the splitter
    lower_splitter.addWidget(self.dashboard_camera_group)

    # Set initial sizes for the horizontal splitter (e.g., 25% automation, 15% events, 20% snapshot, 40% camera)
    lower_splitter.setSizes([300, 200, 250, 450])

    # Add the splitter to the lower layout
    lower_layout.addWidget(lower_splitter)
    
    # Add lower widget to the main vertical splitter
    self.dashboard_splitter.addWidget(self.lower_widget)
    
    # Set initial sizes for the splitter (60% for graph, 40% for camera/lower area)
    self.dashboard_splitter.setSizes([600, 400])
    
    # Add splitter to dashboard layout
    dashboard_layout.addWidget(self.dashboard_splitter, 1)
    
    # Create Camera Tab
    camera_tab = QWidget()
    self.camera_tab = camera_tab
    camera_tab.setStyleSheet(f"background-color: {COLORS.BG_DARK};")
    camera_layout = QHBoxLayout(camera_tab)
    camera_layout.setContentsMargins(15, 0, 15, 0)
    camera_layout.setSpacing(12)
    
    # Define button styles using theme system
    camera_button_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3a4a6a, stop:1 #2a3a5a);
            color: #fff;
            border: 1px solid #4a5a7a;
            border-radius: 6px;
            padding: 6px 12px;
            font-weight: bold;
            font-size: 11px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a5a7a, stop:1 #3a4a6a);
            border: 1px solid #5a6a8a;
        }
        QPushButton:pressed { background: #2a3a5a; }
        QPushButton:disabled { background: #2a2a3a; color: #666; border: 1px solid #3a3a4a; }
    """
    green_button_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2a6a3a, stop:1 #1a5a2a);
            color: #fff;
            border: 1px solid #3a8a4a;
            border-radius: 6px;
            padding: 6px 12px;
            font-weight: bold;
        }
        QPushButton:hover { background: #3a8a4a; }
    """
    red_button_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #6a2a2a, stop:1 #5a1a1a);
            color: #fff;
            border: 1px solid #8a3a3a;
            border-radius: 6px;
            padding: 6px 12px;
            font-weight: bold;
        }
        QPushButton:hover { background: #8a3a3a; }
    """
    
    # Create a splitter for the camera tab
    camera_splitter = QSplitter(Qt.Orientation.Horizontal)
    camera_layout.addWidget(camera_splitter)
    
    # Left side - Camera settings (Global & Hidden Slot Settings)
    camera_settings_container = QWidget()
    camera_settings_container.setMinimumWidth(200) # Reduced from 380
    camera_settings_container.setMaximumWidth(250) # Reduced from 500
    camera_settings_main_layout = QVBoxLayout(camera_settings_container)
    camera_settings_main_layout.setContentsMargins(0, 0, 5, 0)
    camera_settings_main_layout.setSpacing(10)

    # Help and Settings button at the top (Now these are the main global settings)
    global_buttons_group = QGroupBox("Global Settings")
    global_buttons_group.setStyleSheet(GroupBoxStyles.default())
    global_buttons_layout = QVBoxLayout(global_buttons_group)
    
    self.camera_settings_btn = QPushButton("⚙️ Advanced Settings")
    self.camera_settings_btn.setFixedHeight(32)
    self.camera_settings_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    self.camera_settings_btn.setFont(Typography.button())
    self.camera_settings_btn.clicked.connect(self.show_camera_settings_popup)
    global_buttons_layout.addWidget(self.camera_settings_btn)
    
    self.camera_help_btn = QPushButton("❓ Help")
    self.camera_help_btn.setCheckable(True)
    self.camera_help_btn.setFixedHeight(32)
    self.camera_help_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    global_buttons_layout.addWidget(self.camera_help_btn)
    
    self.disconnect_all_btn = QPushButton("🔌 Disconnect All")
    self.disconnect_all_btn.setFixedHeight(32)
    self.disconnect_all_btn.setStyleSheet(ButtonStyles.danger("small"))
    self.disconnect_all_btn.setFont(Typography.button())
    global_buttons_layout.addWidget(self.disconnect_all_btn)
    
    camera_settings_main_layout.addWidget(global_buttons_group)
    camera_settings_main_layout.addStretch()

    # Hidden container for camera-specific tabs (will be moved to popup)
    self.camera_side_tabs_container = QWidget()
    self.camera_side_tabs_container.setVisible(False)
    tabs_layout = QVBoxLayout(self.camera_side_tabs_container)
    tabs_layout.setContentsMargins(0, 0, 0, 0)
    
    # Main Tab Widget for categorized settings
    self.camera_side_tabs = QTabWidget()
    self.camera_side_tabs.setStyleSheet(TabStyles.default())
    tabs_layout.addWidget(self.camera_side_tabs)

    # --- TAB 1: SOURCE & STATUS ---
    source_tab = QWidget()
    source_layout = QVBoxLayout(source_tab)
    source_layout.setContentsMargins(10, 15, 10, 10)
    source_layout.setSpacing(12)
    
    # Camera connection settings - modernized
    camera_connection_group = QGroupBox("📹 Camera Connection")
    camera_connection_group.setStyleSheet(GroupBoxStyles.tight())
    camera_connection_layout = QGridLayout(camera_connection_group)
    camera_connection_layout.setContentsMargins(10, 10, 10, 10)
    camera_connection_layout.setSpacing(10)
    
    # Store the reference to the group box in the main window
    self.camera_connection_group = camera_connection_group
    
    # Camera selection
    camera_connection_layout.addWidget(QLabel("Mode:"), 0, 0)
    self.camera_mode = QComboBox()
    self.camera_mode.addItems(["Local Camera", "NDI Source"])
    self.camera_mode.setStyleSheet(InputStyles.default())
    camera_connection_layout.addWidget(self.camera_mode, 0, 1, 1, 2)
    
    camera_connection_layout.addWidget(QLabel("Source:"), 1, 0)
    source_row_layout = QHBoxLayout()
    source_row_layout.setSpacing(5)
    # Use a very unique name to avoid any shadowing
    self.camera_source_combo = QComboBox() 
    self.camera_id = self.camera_source_combo # Compatibility
    self.camera_id_dropdown = self.camera_source_combo # Compatibility
    self.camera_source_combo.setObjectName("camera_source_dropdown_widget")
    self.camera_source_combo.setStyleSheet(InputStyles.default())
    self.camera_source_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    source_row_layout.addWidget(self.camera_source_combo)
    
    self.camera_refresh_btn = QPushButton("🔄")
    self.camera_refresh_btn.setFixedSize(30, 28)
    self.camera_refresh_btn.setToolTip("Refresh camera list")
    self.camera_refresh_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    source_row_layout.addWidget(self.camera_refresh_btn)
    camera_connection_layout.addLayout(source_row_layout, 1, 1, 1, 2)
    
    # Connect and Apply buttons in their own row
    connect_layout = QHBoxLayout()
    connect_layout.setSpacing(10)
    self.camera_connect_btn = QPushButton("Connect")
    self.camera_connect_btn.setFixedHeight(28)
    self.camera_connect_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.camera_connect_btn.setStyleSheet(ButtonStyles.success("small"))
    connect_layout.addWidget(self.camera_connect_btn)
    
    self.camera_apply_settings_btn = QPushButton("Apply")
    self.camera_apply_settings_btn.setFixedHeight(28)
    self.camera_apply_settings_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.camera_apply_settings_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    self.camera_apply_settings_btn.setToolTip("Apply resolution and FPS changes to the active camera")
    connect_layout.addWidget(self.camera_apply_settings_btn)
    
    camera_connection_layout.addLayout(connect_layout, 2, 1, 1, 2)

    # Auto-connect checkbox for individual camera
    self.camera_auto_connect_checkbox = QCheckBox("Auto-connect at Startup")
    self.camera_auto_connect_checkbox.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 11px;")
    camera_connection_layout.addWidget(self.camera_auto_connect_checkbox, 3, 1, 1, 2)

    # Resolution
    self.camera_resolution_label = QLabel("Res:")
    camera_connection_layout.addWidget(self.camera_resolution_label, 4, 0)
    self.camera_resolution = QComboBox()
    self.camera_resolution.addItems(["640x480", "800x600", "1280x720", "1920x1080"])
    self.camera_resolution.setStyleSheet(InputStyles.default())
    camera_connection_layout.addWidget(self.camera_resolution, 4, 1, 1, 2)

    # Framerate
    camera_connection_layout.addWidget(QLabel("FPS:"), 5, 0)
    self.camera_framerate = QComboBox()
    self.camera_framerate.addItems(["15", "30", "60"])
    self.camera_framerate.setStyleSheet(InputStyles.default())
    camera_connection_layout.addWidget(self.camera_framerate, 5, 1, 1, 2)

    # FPS Display
    fps_label = QLabel("Actual Rate:")
    fps_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")
    camera_connection_layout.addWidget(fps_label, 6, 0)
    
    self.camera_fps_display = QLabel("0.0 / 0.0 FPS")
    self.camera_fps_display.setStyleSheet(f"color: {COLORS.PRIMARY_LIGHT}; font-weight: bold;")
    self.camera_fps_display.setToolTip("Actual FPS / Target FPS")
    camera_connection_layout.addWidget(self.camera_fps_display, 6, 1, 1, 2)
    
    # Sync Note
    sync_note = QLabel("Note: If actual FPS is lower than target, frames are duplicated.")
    sync_note.setWordWrap(True)
    sync_note.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
    camera_connection_layout.addWidget(sync_note, 7, 0, 1, 3)
    
    # Recording settings for individual cameras
    recording_settings_group = QGroupBox("⏺️ Recording Settings")
    recording_settings_group.setStyleSheet(GroupBoxStyles.tight())
    recording_settings_layout = QGridLayout(recording_settings_group)
    recording_settings_layout.setContentsMargins(10, 10, 10, 10)
    recording_settings_layout.setSpacing(8)
    
    self.record_video_checkbox = QCheckBox("Record Video")
    self.record_video_checkbox.setChecked(True)
    recording_settings_layout.addWidget(self.record_video_checkbox, 0, 0)
    
    self.record_audio_checkbox = QCheckBox("Record Audio")
    self.record_audio_checkbox.setChecked(False)
    recording_settings_layout.addWidget(self.record_audio_checkbox, 0, 1)

    recording_settings_layout.addWidget(QLabel("Audio Device:"), 1, 0)
    self.camera_audio_device = QComboBox()
    self.camera_audio_device.addItem("Default Mic", -1)
    self.camera_audio_device.setStyleSheet(InputStyles.default())
    recording_settings_layout.addWidget(self.camera_audio_device, 1, 1)
    
    # Add to source layout
    source_layout.addWidget(camera_connection_group)
    source_layout.addWidget(recording_settings_group)
    
    # Motion indicator in camera tab - modernized
    motion_status_group = QGroupBox("🔍 Motion Detection")
    motion_status_group.setStyleSheet(GroupBoxStyles.tight())
    motion_status_layout = QHBoxLayout(motion_status_group)
    motion_status_layout.setContentsMargins(10, 10, 10, 10)
    
    motion_label = QLabel("Status:")
    motion_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")
    motion_status_layout.addWidget(motion_label)
    self.motion_detection_indicator = QLabel()
    self.motion_detection_indicator.setFixedSize(16, 16)
    self.motion_detection_indicator.setStyleSheet(StatusIndicator.get("online", glow=True))
    self.motion_detection_indicator.setToolTip("Green: No motion | Red: Motion detected")
    motion_status_layout.addWidget(self.motion_detection_indicator)
    motion_status_text = QLabel("Idle")
    motion_status_text.setStyleSheet(StatusText.success())
    motion_status_layout.addWidget(motion_status_text)
    motion_status_layout.addStretch()

    source_layout.addStretch()
    self.camera_side_tabs.addTab(source_tab, "Source")
    
    # --- TAB 2: ADJUSTMENTS ---
    adjust_tab = QWidget()
    adjust_layout = QVBoxLayout(adjust_tab)
    adjust_layout.setContentsMargins(10, 15, 10, 10)
    adjust_layout.setSpacing(12)

    # Camera focus and exposure controls - modernized
    self.camera_controls_group = QGroupBox("🎛️ Camera Controls")
    self.camera_controls_group.setStyleSheet(GroupBoxStyles.tight())
    camera_controls_layout = QGridLayout(self.camera_controls_group)
    camera_controls_layout.setContentsMargins(10, 10, 10, 10)
    camera_controls_layout.setSpacing(10)
    
    # Modern slider style
    slider_style = f"""
        QSlider::groove:horizontal {{
            height: 6px;
            background: {COLORS.BG_INPUT};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {COLORS.PRIMARY};
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
        }}
        QSlider::handle:horizontal:hover {{
            background: {COLORS.PRIMARY_LIGHT};
        }}
        QSlider::sub-page:horizontal {{
            background: {COLORS.PRIMARY};
            border-radius: 3px;
        }}
    """
    
    # Manual focus controls
    self.camera_tab_manual_focus = QCheckBox("Manual Focus")
    self.camera_tab_manual_focus.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-weight: 500;")
    self.camera_tab_manual_focus.setToolTip("Enable to manually control camera focus")
    initial_manual_focus = self.settings.value("camera/manual_focus", "true").lower() == "true"
    self.camera_tab_manual_focus.setChecked(initial_manual_focus)
    camera_controls_layout.addWidget(self.camera_tab_manual_focus, 0, 0, 1, 3)
    
    # Focus slider with value label
    focus_slider_layout = QHBoxLayout()
    self.camera_tab_focus_slider = QSlider(Qt.Orientation.Horizontal)
    self.camera_tab_focus_slider.setStyleSheet(slider_style)
    self.camera_tab_focus_slider.setMinimum(0)
    self.camera_tab_focus_slider.setMaximum(255)
    self.camera_tab_focus_slider.setValue(int(self.settings.value("camera/focus_value", "0")))
    self.camera_tab_focus_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    self.camera_tab_focus_slider.setTickInterval(50)
    self.camera_tab_focus_slider.setEnabled(initial_manual_focus)
    focus_slider_layout.addWidget(self.camera_tab_focus_slider, 1)
    
    # Value display for focus
    self.camera_tab_focus_value = QLabel(str(self.camera_tab_focus_slider.value()))
    self.camera_tab_focus_value.setStyleSheet(f"color: {COLORS.PRIMARY_LIGHT}; font-weight: bold; min-width: 30px;")
    self.camera_tab_focus_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    focus_slider_layout.addWidget(self.camera_tab_focus_value)
    camera_controls_layout.addLayout(focus_slider_layout, 1, 0, 1, 3)
    
    # Manual exposure controls
    self.camera_tab_manual_exposure = QCheckBox("Manual Exposure")
    self.camera_tab_manual_exposure.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-weight: 500;")
    self.camera_tab_manual_exposure.setToolTip("Enable to manually control camera exposure")
    initial_manual_exposure = self.settings.value("camera/manual_exposure", "true").lower() == "true"
    self.camera_tab_manual_exposure.setChecked(initial_manual_exposure)
    camera_controls_layout.addWidget(self.camera_tab_manual_exposure, 2, 0, 1, 3)
    
    # Exposure slider with value label
    exposure_slider_layout = QHBoxLayout()
    self.camera_tab_exposure_slider = QSlider(Qt.Orientation.Horizontal)
    self.camera_tab_exposure_slider.setStyleSheet(slider_style)
    self.camera_tab_exposure_slider.setMinimum(-13)  # Exposure values can be negative
    self.camera_tab_exposure_slider.setMaximum(13)
    self.camera_tab_exposure_slider.setValue(int(self.settings.value("camera/exposure_value", "0")))
    self.camera_tab_exposure_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    self.camera_tab_exposure_slider.setTickInterval(5)
    self.camera_tab_exposure_slider.setEnabled(initial_manual_exposure)
    exposure_slider_layout.addWidget(self.camera_tab_exposure_slider, 1)
    
    # Value display for exposure
    self.camera_tab_exposure_value = QLabel(str(self.camera_tab_exposure_slider.value()))
    self.camera_tab_exposure_value.setStyleSheet(f"color: {COLORS.PRIMARY_LIGHT}; font-weight: bold; min-width: 30px;")
    self.camera_tab_exposure_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    exposure_slider_layout.addWidget(self.camera_tab_exposure_value)
    camera_controls_layout.addLayout(exposure_slider_layout, 3, 0, 1, 3)
    
    # Add camera controls group to adjust layout
    adjust_layout.addWidget(self.camera_controls_group)
    
    # Motion Detection Settings for the active camera
    motion_settings_group = QGroupBox("🔍 Motion Detection")
    motion_settings_group.setStyleSheet(GroupBoxStyles.tight())
    motion_settings_layout = QGridLayout(motion_settings_group)
    motion_settings_layout.setContentsMargins(10, 10, 10, 10)
    motion_settings_layout.setSpacing(10)
    
    self.motion_detection_enabled = QCheckBox("Enable Motion Detection")
    self.motion_detection_enabled.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-weight: 500;")
    motion_settings_layout.addWidget(self.motion_detection_enabled, 0, 0, 1, 2)
    
    motion_settings_layout.addWidget(QLabel("Sensitivity:"), 1, 0)
    self.motion_detection_sensitivity = QSlider(Qt.Orientation.Horizontal)
    self.motion_detection_sensitivity.setStyleSheet(slider_style)
    self.motion_detection_sensitivity.setRange(1, 100)
    self.motion_detection_sensitivity.setValue(20)
    motion_settings_layout.addWidget(self.motion_detection_sensitivity, 1, 1)
    
    motion_settings_layout.addWidget(QLabel("Min Area:"), 2, 0)
    self.motion_detection_min_area = QSpinBox()
    self.motion_detection_min_area.setStyleSheet(InputStyles.default())
    self.motion_detection_min_area.setRange(10, 10000)
    self.motion_detection_min_area.setSingleStep(100)
    self.motion_detection_min_area.setValue(500)
    motion_settings_layout.addWidget(self.motion_detection_min_area, 2, 1)
    
    adjust_layout.addStretch()
    self.camera_side_tabs.addTab(adjust_tab, "Adjust")

    # --- TAB 3: MOTION DETECTION ---
    motion_tab = QWidget()
    motion_layout = QVBoxLayout(motion_tab)
    motion_layout.setContentsMargins(10, 15, 10, 10)
    motion_layout.setSpacing(12)
    
    # Update group box titles
    motion_status_group.setTitle("🔍 Motion Status")
    motion_settings_group.setTitle("🔍 Motion Configuration")
    
    motion_layout.addWidget(motion_status_group)
    motion_layout.addWidget(motion_settings_group)
    motion_layout.addStretch()
    self.camera_side_tabs.addTab(motion_tab, "Motion Detection")

    # --- TAB 4: OVERLAY ---
    overlay_tab = QWidget()
    overlay_main_layout = QVBoxLayout(overlay_tab)
    overlay_main_layout.setContentsMargins(0, 0, 0, 0)

    # Use a ScrollArea ONLY for the overlay tab
    overlay_scroll = QScrollArea()
    overlay_scroll.setWidgetResizable(True)
    overlay_scroll.setFrameShape(QFrame.Shape.NoFrame)
    overlay_scroll.setStyleSheet(ScrollStyles.default())
    
    overlay_container = QWidget()
    overlay_layout = QVBoxLayout(overlay_container)
    overlay_layout.setContentsMargins(10, 15, 10, 10)
    overlay_layout.setSpacing(10)

    # Use a grid for basic overlay properties
    overlay_props_widget = QWidget()
    overlay_props_layout = QGridLayout(overlay_props_widget)
    overlay_props_layout.setContentsMargins(0, 0, 0, 0)
    overlay_props_layout.setSpacing(8)

    # Overlay selection
    overlay_props_layout.addWidget(QLabel("Overlay:"), 0, 0)
    self.overlay_selector = QComboBox()
    self.overlay_selector.setStyleSheet(InputStyles.default())
    overlay_props_layout.addWidget(self.overlay_selector, 0, 1)

    # Text size (font scale)
    overlay_props_layout.addWidget(QLabel("Font Scale:"), 1, 0)
    self.overlay_font_scale = QDoubleSpinBox()
    self.overlay_font_scale.setStyleSheet(InputStyles.default())
    self.overlay_font_scale.setRange(0.1, 3.0)
    self.overlay_font_scale.setSingleStep(0.1)
    self.overlay_font_scale.setValue(0.7)
    overlay_props_layout.addWidget(self.overlay_font_scale, 1, 1)

    lbl_thick = QLabel("Thickness:")
    lbl_thick.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
    overlay_props_layout.addWidget(lbl_thick, 2, 0)
    self.overlay_thickness = QSpinBox()
    self.overlay_thickness.setStyleSheet(InputStyles.default())
    self.overlay_thickness.setRange(1, 5)
    self.overlay_thickness.setValue(2)
    overlay_props_layout.addWidget(self.overlay_thickness, 2, 1)
    
    overlay_layout.addWidget(overlay_props_widget)

    # Text and Background color groups
    text_color_group = QGroupBox("Text Color")
    text_color_group.setStyleSheet(GroupBoxStyles.compact())
    text_color_layout = QHBoxLayout(text_color_group)
    text_color_layout.setContentsMargins(8, 10, 8, 8)
    self.text_color_preview = QFrame()
    self.text_color_preview.setFixedSize(50, 18)
    self.text_color_preview.setStyleSheet(f"background-color: rgb(0, 255, 0); border: 1px solid {COLORS.BORDER_HOVER}; border-radius: 4px;")
    text_color_layout.addWidget(self.text_color_preview)
    self.text_color_picker_btn = QPushButton("Color")
    self.text_color_picker_btn.setFixedSize(65, 26)
    self.text_color_picker_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    self.text_color_picker_btn.clicked.connect(self.choose_text_color)
    text_color_layout.addWidget(self.text_color_picker_btn)
    text_color_layout.addStretch()
    overlay_layout.addWidget(text_color_group)

    bg_color_group = QGroupBox("Background Color")
    bg_color_group.setStyleSheet(GroupBoxStyles.compact())
    bg_color_layout = QVBoxLayout(bg_color_group)
    bg_color_layout.setContentsMargins(8, 10, 8, 8)
    
    bg_top_row = QHBoxLayout()
    self.bg_color_preview = QFrame()
    self.bg_color_preview.setFixedSize(50, 18)
    self.bg_color_preview.setStyleSheet(f"background-color: rgba(0, 0, 0, 0.7); border: 1px solid {COLORS.BORDER_HOVER}; border-radius: 4px;")
    bg_top_row.addWidget(self.bg_color_preview)
    self.bg_color_picker_btn = QPushButton("Color")
    self.bg_color_picker_btn.setFixedSize(65, 26)
    self.bg_color_picker_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    self.bg_color_picker_btn.clicked.connect(self.choose_bg_color)
    bg_top_row.addWidget(self.bg_color_picker_btn)
    bg_top_row.addStretch()
    bg_color_layout.addLayout(bg_top_row)

    bg_opacity_layout = QHBoxLayout()
    opacity_label = QLabel("Opacity:")
    opacity_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 11px;")
    bg_opacity_layout.addWidget(opacity_label)
    self.overlay_bg_alpha = QSpinBox()
    self.overlay_bg_alpha.setStyleSheet(InputStyles.default())
    self.overlay_bg_alpha.setRange(0, 100)
    self.overlay_bg_alpha.setValue(70)
    bg_opacity_layout.addWidget(self.overlay_bg_alpha)
    bg_color_layout.addLayout(bg_opacity_layout)
    overlay_layout.addWidget(bg_color_group)

    # Store hidden RGB values
    self.overlay_text_color_r = QSpinBox(); self.overlay_text_color_r.setVisible(False); self.overlay_text_color_r.setRange(0, 255)
    self.overlay_text_color_g = QSpinBox(); self.overlay_text_color_g.setVisible(False); self.overlay_text_color_g.setRange(0, 255)
    self.overlay_text_color_b = QSpinBox(); self.overlay_text_color_b.setVisible(False); self.overlay_text_color_b.setRange(0, 255)
    self.overlay_bg_color_r = QSpinBox(); self.overlay_bg_color_r.setVisible(False); self.overlay_bg_color_r.setRange(0, 255)
    self.overlay_bg_color_g = QSpinBox(); self.overlay_bg_color_g.setVisible(False); self.overlay_bg_color_g.setRange(0, 255)
    self.overlay_bg_color_b = QSpinBox(); self.overlay_bg_color_b.setVisible(False); self.overlay_bg_color_b.setRange(0, 255)
    self.overlay_bg_opacity = self.overlay_bg_alpha

    # Advanced Collapsibles
    label_style = f"color: {COLORS.TEXT_SECONDARY}; font-weight: 500; font-size: 11px;"
    
    text_content_collapsible = CollapsibleBox("Text Content")
    text_content_layout = QGridLayout()
    text_content_layout.setContentsMargins(10, 10, 10, 10)
    text_content_layout.addWidget(QLabel("Format:"), 0, 0)
    self.overlay_text_content = QLineEdit("Sample text")
    self.overlay_text_content.setStyleSheet(InputStyles.default())
    text_content_layout.addWidget(self.overlay_text_content, 0, 1)
    self.overlay_data_source = QComboBox()
    self.overlay_data_source.addItems(["Static Text", "Date/Time", "Timestamp", "Sensor Data", "Counter", "Calculated"])
    text_content_layout.addWidget(QLabel("Source:"), 1, 0); text_content_layout.addWidget(self.overlay_data_source, 1, 1)
    self.overlay_prefix = QLineEdit(); text_content_layout.addWidget(QLabel("Prefix:"), 2, 0); text_content_layout.addWidget(self.overlay_prefix, 2, 1)
    self.overlay_suffix = QLineEdit(); text_content_layout.addWidget(QLabel("Suffix:"), 3, 0); text_content_layout.addWidget(self.overlay_suffix, 3, 1)
    text_content_collapsible.setContentLayout(text_content_layout)
    overlay_layout.addWidget(text_content_collapsible)

    format_collapsible = CollapsibleBox("Data Format")
    format_layout = QGridLayout()
    format_layout.setContentsMargins(10, 10, 10, 10)
    self.overlay_format = QLineEdit(); self.overlay_format.setPlaceholderText("%.2f")
    format_layout.addWidget(QLabel("Format:"), 0, 0); format_layout.addWidget(self.overlay_format, 0, 1)
    self.overlay_precision = QSpinBox(); self.overlay_precision.setRange(0, 10)
    format_layout.addWidget(QLabel("Prec:"), 1, 0); format_layout.addWidget(self.overlay_precision, 1, 1)
    format_collapsible.setContentLayout(format_layout)
    overlay_layout.addWidget(format_collapsible)

    dim_collapsible = CollapsibleBox("Dimensions")
    dim_layout = QGridLayout(); dim_layout.setContentsMargins(10, 10, 10, 10)
    self.overlay_width = QSpinBox(); self.overlay_width.setRange(10, 800)
    dim_layout.addWidget(QLabel("W:"), 0, 0); dim_layout.addWidget(self.overlay_width, 0, 1)
    self.overlay_height = QSpinBox(); self.overlay_height.setRange(10, 600)
    dim_layout.addWidget(QLabel("H:"), 1, 0); dim_layout.addWidget(self.overlay_height, 1, 1)
    dim_collapsible.setContentLayout(dim_layout)
    overlay_layout.addWidget(dim_collapsible)

    # Action buttons
    btns_layout = QHBoxLayout(); btns_layout.setSpacing(10); btns_layout.setContentsMargins(0, 10, 0, 0)
    self.apply_overlay_settings_btn = QPushButton("Apply"); self.apply_overlay_settings_btn.setStyleSheet(ButtonStyles.success("small"))
    self.remove_overlay_btn = QPushButton("Remove"); self.remove_overlay_btn.setStyleSheet(ButtonStyles.danger("small"))
    btns_layout.addWidget(self.apply_overlay_settings_btn); btns_layout.addWidget(self.remove_overlay_btn)
    overlay_layout.addLayout(btns_layout)
    overlay_layout.addStretch()

    overlay_scroll.setWidget(overlay_container)
    overlay_main_layout.addWidget(overlay_scroll)
    self.camera_side_tabs.addTab(overlay_tab, "Overlay")

    # Store references
    self.overlay_text_content_group = text_content_collapsible
    self.overlay_format_group = format_collapsible
    self.overlay_dimensions_group = dim_collapsible

    # Finally add camera settings container to the splitter
    camera_splitter.addWidget(camera_settings_container)
    
    # Right side - Camera view and controls
    camera_view_container = QWidget()
    camera_view_layout = QVBoxLayout(camera_view_container)
    camera_view_layout.setContentsMargins(10, 0, 0, 0)
    camera_view_layout.setSpacing(10)
    
    # Main content area with thumbnails on the left and large view on the right
    content_hbox = QHBoxLayout()
    
    # Vertical thumbnail list
    thumb_scroll = QScrollArea()
    thumb_scroll.setFixedWidth(200) # Increased from 180 to fit longer button text
    thumb_scroll.setWidgetResizable(True)
    thumb_scroll.setFrameShape(QFrame.Shape.NoFrame)
    thumb_container = QWidget()
    thumb_vbox = QVBoxLayout(thumb_container)
    thumb_vbox.setContentsMargins(0, 0, 5, 0)
    thumb_vbox.setSpacing(10)
    
    self.camera_preview_labels = []
    for i in range(4):
        slot_frame = QFrame()
        slot_frame.setStyleSheet(f"background: {COLORS.BG_DARK}; border: 1px solid {COLORS.BORDER_DEFAULT}; border-radius: 4px;")
        slot_layout = QVBoxLayout(slot_frame)
        slot_layout.setContentsMargins(2, 2, 2, 2)
        
        lbl = QLabel(f"C{i+1}")
        lbl.setFixedSize(180, 135) # Slightly larger
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background: black; color: white;")
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        lbl.setToolTip(f"Click to view Camera {i+1}")
        # Make the preview clickable
        lbl.mousePressEvent = lambda e, idx=i: self.camera_controller.set_main_view(idx)
        slot_layout.addWidget(lbl)
        self.camera_preview_labels.append(lbl)
        
        cfg_btn = QPushButton(f"Configure Camera {i+1}")
        cfg_btn.setFixedHeight(28)
        cfg_btn.setStyleSheet(camera_button_style)
        def handle_cfg_click(checked, idx=i):
            self.camera_controller.set_active_config_slot(idx)
            self.show_camera_config_dialog(idx)
        cfg_btn.clicked.connect(handle_cfg_click)
        slot_layout.addWidget(cfg_btn)
        
        thumb_vbox.addWidget(slot_frame)
    thumb_vbox.addStretch()
    thumb_scroll.setWidget(thumb_container)
    content_hbox.addWidget(thumb_scroll)
    
    # Large Camera view
    camera_view_frame = QFrame()
    camera_view_frame.setStyleSheet(f"background: {COLORS.BG_CARD}; border: 2px solid {COLORS.BORDER_DEFAULT}; border-radius: 8px;")
    camera_frame_layout = QVBoxLayout(camera_view_frame)
    camera_frame_layout.setContentsMargins(4, 4, 4, 4)
    
    self.camera_label = QLabel("📷 No camera connected")
    self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.camera_label.setStyleSheet(f"background-color: {COLORS.BG_DARK}; color: {COLORS.TEXT_MUTED}; font-size: 16px; border-radius: 8px;")
    self.camera_label.setMinimumSize(320, 240)
    self.camera_label.setMouseTracking(True)
    self.camera_label.mousePressEvent = self.camera_mouse_press
    self.camera_label.mouseReleaseEvent = self.camera_mouse_release
    self.camera_label.mouseMoveEvent = self.camera_mouse_move
    
    camera_frame_layout.addWidget(self.camera_label)
    content_hbox.addWidget(camera_view_frame, 1)
    camera_view_layout.addLayout(content_hbox)
    
    # Camera controls - modern button bar with fixed height
    camera_controls_bar = QFrame()
    camera_controls_bar.setFixedHeight(50)
    camera_controls_bar.setStyleSheet(f"""
        QFrame {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {COLORS.BG_ELEVATED}, stop:1 #1e1e35);
            border: 1px solid #3a3a5a;
            border-radius: 8px;
        }}
    """)
    camera_controls = QHBoxLayout(camera_controls_bar)
    camera_controls.setContentsMargins(12, 8, 12, 8)
    camera_controls.setSpacing(8)
    
    # Snapshot button
    self.snapshot_btn = QPushButton("📸 Snapshot")
    self.snapshot_btn.setFixedSize(110, 32)
    self.snapshot_btn.setStyleSheet(camera_button_style)
    self.snapshot_btn.setEnabled(False)
    
    # Record button
    self.record_btn = QPushButton("⏺️ Record")
    self.record_btn.setFixedSize(100, 32)
    self.record_btn.setStyleSheet(camera_button_style)
    self.record_btn.setEnabled(False)
    
    # Add overlay button
    self.add_overlay_btn = QPushButton("🏷️ Add Overlay")
    self.add_overlay_btn.setFixedSize(120, 32)
    self.add_overlay_btn.setStyleSheet(camera_button_style)
    self.add_overlay_btn.setEnabled(False)
    
    # Add buttons to layout
    camera_controls.addWidget(self.snapshot_btn)
    camera_controls.addWidget(self.record_btn)
    camera_controls.addWidget(self.add_overlay_btn)

    # Audio controls for camera/replay
    camera_controls.addWidget(QLabel("Vol.:"))
    self.camera_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.camera_volume_slider.setRange(0, 100)
    self.camera_volume_slider.setValue(100)
    self.camera_volume_slider.setFixedWidth(120) # Slightly reduced from 140
    self.camera_volume_slider.setEnabled(True)
    camera_controls.addWidget(self.camera_volume_slider)
    self.camera_mute_checkbox = QCheckBox("🔇")
    self.camera_mute_checkbox.setToolTip("Mute")
    self.camera_mute_checkbox.setEnabled(True)
    camera_controls.addWidget(self.camera_mute_checkbox)

    camera_controls.addStretch()
    
    camera_view_layout.addWidget(camera_controls_bar)
    
    # Add camera settings container to the splitter
    camera_splitter.addWidget(camera_settings_container)
    
    # Add camera view container to the splitter
    camera_splitter.addWidget(camera_view_container)
    
    # Right side: Help panel (import HelpPanel and get_help_content)
    from app.ui.tools.help_panel import HelpPanel, get_help_content
    
    # Create a container for the help panel to match height
    self.camera_help_container = QWidget()
    self.camera_help_container.setVisible(False)
    self.camera_help_container.setFixedWidth(320)
    camera_help_container_layout = QVBoxLayout(self.camera_help_container)
    camera_help_container_layout.setContentsMargins(5, 0, 0, 0)
    
    self.camera_help_panel = HelpPanel("Camera & NDI Help")
    camera_help_container_layout.addWidget(self.camera_help_panel)
    
    # Load camera help content
    camera_help_content = get_help_content("camera")
    self.camera_help_panel.clear_sections()
    for section in camera_help_content.get("sections", []):
        self.camera_help_panel.add_section(
            section.get("title", ""),
            section.get("content", ""),
            section.get("icon", "📖")
        )
    # Expand first section by default
    if self.camera_help_panel.sections:
        self.camera_help_panel.sections[0].expand()
    
    # Add help container to the splitter
    camera_splitter.addWidget(self.camera_help_container)
    
    # Connect help button and panel close
    def toggle_camera_help():
        is_visible = not self.camera_help_container.isVisible()
        self.camera_help_container.setVisible(is_visible)
        self.camera_help_btn.setChecked(is_visible)
    
    self.camera_help_btn.clicked.connect(toggle_camera_help)
    self.camera_help_panel.close_requested.connect(toggle_camera_help)
    
    # Set initial sizes for the splitter (20% for settings, 80% for camera view)
    camera_splitter.setSizes([200, 800, 0])
    
    # Video tab
    video_tab = QWidget()
    self.video_tab = video_tab
    video_layout = QVBoxLayout(video_tab)
    video_layout.setContentsMargins(10, 0, 10, 0)
    
    # Video player section
    video_player_group = QGroupBox("Video Player")
    video_player_group.setStyleSheet(GroupBoxStyles.section())
    video_player_layout = QVBoxLayout(video_player_group)
    
    # Video display area
    self.video_display = QVideoWidget()
    self.video_display.setMinimumHeight(200) # Reduced from 400 to allow window shrinking
    self.video_display.setStyleSheet("background-color: #222; border: 1px solid #444;")
    video_player_layout.addWidget(self.video_display)
    
    # Video controls
    video_controls_layout = QHBoxLayout()
    
    self.play_video_btn = QPushButton("Play")
    self.play_video_btn.setMinimumHeight(30)
    self.play_video_btn.setEnabled(False)
    video_controls_layout.addWidget(self.play_video_btn)
    
    self.pause_video_btn = QPushButton("Pause")
    self.pause_video_btn.setMinimumHeight(30)
    self.pause_video_btn.setEnabled(False)
    video_controls_layout.addWidget(self.pause_video_btn)
    
    self.stop_video_btn = QPushButton("Stop")
    self.stop_video_btn.setMinimumHeight(30)
    self.stop_video_btn.setEnabled(False)
    video_controls_layout.addWidget(self.stop_video_btn)

    # Volume controls
    self.video_volume_label = QLabel("Vol.:")
    video_controls_layout.addWidget(self.video_volume_label)
    
    self.video_volume_slider = QSlider(Qt.Orientation.Horizontal)
    self.video_volume_slider.setRange(0, 100)
    self.video_volume_slider.setValue(100)
    self.video_volume_slider.setFixedWidth(120) # Slightly reduced from 140
    video_controls_layout.addWidget(self.video_volume_slider)
    
    self.video_mute_checkbox = QCheckBox("🔇")
    self.video_mute_checkbox.setToolTip("Mute")
    video_controls_layout.addWidget(self.video_mute_checkbox)
    
    video_player_layout.addLayout(video_controls_layout)
    
    # Video information
    video_info_layout = QFormLayout()
    self.video_filename_label = QLabel("No file loaded")
    video_info_layout.addRow("File:", self.video_filename_label)
    
    self.video_duration_label = QLabel("--:--")
    video_info_layout.addRow("Duration:", self.video_duration_label)
    
    self.video_position_label = QLabel("--:--")
    video_info_layout.addRow("Position:", self.video_position_label)
    
    video_player_layout.addLayout(video_info_layout)
    
    # Add video player group to the layout
    video_layout.addWidget(video_player_group)
    
    # Create Sensors Tab
    sensors_tab = QWidget()
    self.sensors_tab = sensors_tab
    sensors_layout = QHBoxLayout(sensors_tab)
    sensors_layout.setContentsMargins(10, 0, 10, 0)
    sensors_layout.setSpacing(10)
    
    # Main content container
    sensors_main_container = QWidget()
    sensors_main_layout = QVBoxLayout(sensors_main_container)
    sensors_main_layout.setContentsMargins(0, 0, 0, 0)
    sensors_main_layout.setSpacing(10)
    
    # Horizontal splitter for devices (left) and sensor management (right)
    self.sensors_splitter = QSplitter(Qt.Orientation.Horizontal)
    self.sensors_splitter.setChildrenCollapsible(True)
    self.sensors_splitter.setHandleWidth(2)
    self.sensors_splitter.setStyleSheet(f"""
        QSplitter::handle {{
            background-color: {COLORS.BORDER_DEFAULT};
        }}
        QSplitter::handle:hover {{
            background-color: {COLORS.PRIMARY};
        }}
    """)
    
    # Left sidebar container for devices and info text
    sidebar_wrapper = QWidget()
    sidebar_layout = QVBoxLayout(sidebar_wrapper)
    sidebar_layout.setContentsMargins(0, 0, 0, 0)
    sidebar_layout.setSpacing(10)

    # Device cards section with proper styling (matching automation tab)
    devices_section = QGroupBox("Interfaces")
    devices_section.setStyleSheet(GroupBoxStyles.default())
    devices_section_layout = QVBoxLayout(devices_section)
    devices_section_layout.setContentsMargins(10, 10, 10, 10)
    devices_section_layout.setSpacing(8)
    
    # Device cards container with vertical layout for stacking cards
    devices_cards_container = QWidget()
    devices_cards_container.setStyleSheet("background: transparent; border: none;")
    devices_cards_layout = QGridLayout(devices_cards_container)
    devices_cards_layout.setContentsMargins(0, 0, 0, 0)
    devices_cards_layout.setSpacing(8)
    devices_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    
    # Custom Interfaces Info - Now moved outside the group box later
    custom_interface_info = QLabel("💡 Create custom interfaces with small Python scripts. See Help for info.")
    custom_interface_info.setWordWrap(True)
    custom_interface_info.setStyleSheet("color: #666; font-size: 10px; margin-left: 5px; margin-right: 5px;")
    
    # Modern card style for devices - matching theme system
    device_card_style = CardStyles.device_card(connected=False)
    
    # Card size - reduced to allow better height compression
    card_width, card_height = 90, 78 
    
    # Card content styles
    card_label_style = "font-size: 10px; font-weight: bold; color: #fff; border: none; background-color: transparent;"
    card_status_style = "font-size: 9px; color: #888; border: none; background-color: transparent;"
    card_icon_style = "font-size: 28px; background-color: transparent; border: none;"
    device_icon_height = 36
    device_image_icon_size = 34
    
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Map for built-in interface settings popups
    settings_popups = {
        "Arduino": getattr(self, "show_arduino_settings_popup", None),
        "LabJack": getattr(self, "show_labjack_settings_popup", None),
        "Optical": getattr(self, "show_optical_sensor_popup", None),
        "Audio": getattr(self, "show_audio_sensor_popup", None),
        "MQTT": getattr(self, "show_mqtt_settings_popup", None),
        "Read CSV": getattr(self, "show_csv_settings_popup", None),
        "Serial": getattr(self, "show_other_settings_popup", None)
    }

    # Helper to create an interface card
    def create_card(name, icon_resource, popup_func, is_plugin=False, is_outbound=False):
        container = QFrame()
        container.setFixedSize(card_width, card_height)
        
        # Use specific style based on interface type
        if is_outbound:
            container.setStyleSheet(CardStyles.outbound_plugin_card(connected=False))
        elif is_plugin:
            container.setStyleSheet(CardStyles.plugin_card(connected=False))
        else:
            container.setStyleSheet(device_card_style)
            
        container.setCursor(Qt.CursorShape.PointingHandCursor)
        card_layout = QVBoxLayout(container)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(2)
        
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedHeight(device_icon_height)
        icon_label.setStyleSheet("background-color: transparent; border: none;")
        
        # 1. Check if icon_resource is an absolute path (resolved plugin icon)
        if icon_resource and os.path.isabs(icon_resource) and os.path.exists(icon_resource):
            pixmap = QPixmap(icon_resource)
            scaled_pixmap = pixmap.scaled(device_image_icon_size, device_image_icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
            
        # 2. Check for custom plugin icon in plugins/ folder (display name.png) - LEGACY CONVENTION
        elif os.path.exists(os.path.join(os.getcwd(), "plugins", f"{name}.png")):
            custom_icon_path = os.path.join(os.getcwd(), "plugins", f"{name}.png")
            pixmap = QPixmap(custom_icon_path)
            scaled_pixmap = pixmap.scaled(device_image_icon_size, device_image_icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
            
        # 3. Check if icon is an image file or an emoji
        elif icon_resource:
            if icon_resource.endswith(".png") or icon_resource.endswith(".svg"):
                img_path = os.path.join(ui_dir, icon_resource)
                if os.path.exists(img_path):
                    pixmap = QPixmap(img_path)
                    scaled_pixmap = pixmap.scaled(device_image_icon_size, device_image_icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    icon_label.setPixmap(scaled_pixmap)
                else:
                    icon_label.setText("🔌")
                    icon_label.setStyleSheet(card_icon_style)
            else:
                icon_label.setText(icon_resource)
                icon_label.setStyleSheet(card_icon_style)
        
        # 4. If no icon provided and it's NOT a plugin, show fallback
        elif not is_plugin:
            icon_label.setText("🔌")
            icon_label.setStyleSheet(card_icon_style)
        else:
            # Explicitly clear icon for plugins if nothing else matches
            # This ensures no lightning bolt or plug is shown by default
            icon_label.setText("")
            icon_label.setPixmap(QPixmap())
            icon_label.setStyleSheet("background-color: transparent; border: none;")
        
        card_layout.addWidget(icon_label)
        
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(card_label_style)
        card_layout.addWidget(name_label)
        
        status_label = QLabel("Not connected")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet(card_status_style)
        status_label.setObjectName(f"{name.lower().replace(' ', '_')}_status_label")
        card_layout.addWidget(status_label)
        
        if popup_func:
            def handle_mouse_press(event):
                # Ensure we don't return the result of popup_func() to Qt
                # as it can cause sipBadCatcherResult if it's a boolean
                popup_func()
                # Accept the event
                if event:
                    event.accept()
            container.mousePressEvent = handle_mouse_press
        
        return container, status_label

    # Discover and add cards for all registered interfaces
    InterfaceRegistry.initialize()
    interfaces = InterfaceRegistry.get_interfaces()
    
    self.interface_status_labels = {} # Store labels for status updates
    self.interface_connect_buttons = {} # Store connect buttons for status updates
    
    # Sort interfaces to keep consistent order (Arduino first, etc.)
    ordered_names = ["Arduino", "LabJack", "Serial", "Read CSV", "Optical", "Audio", "MQTT"]
    all_names = list(interfaces.keys())
    sorted_names = [n for n in ordered_names if n in all_names] + [n for n in all_names if n not in ordered_names]

    for i, name in enumerate(sorted_names):
        interface_class = interfaces[name]
        icon = getattr(interface_class, "ICON", "🔌")
        
        # Detect if it's a plugin based on module name
        # Built-in interfaces are in app.core.interfaces.*
        # Plugins are imported from the plugins/ directory directly
        module_name = getattr(interface_class, "__module__", "")
        is_plugin = not module_name.startswith("app.core.interfaces")
        
        print(f"DEBUG UI: Interface '{name}' module='{module_name}' is_plugin={is_plugin}")
        
        # Handle icons for plugins
        if is_plugin:
            # 1. Resolve icon path if it's a file
            if icon and (icon.endswith(".png") or icon.endswith(".svg")):
                try:
                    import inspect
                    plugin_file = inspect.getfile(interface_class)
                    plugin_dir = os.path.dirname(plugin_file)
                    potential_path = os.path.join(plugin_dir, icon)
                    if os.path.exists(potential_path):
                        icon = potential_path # Pass absolute path to create_card
                except Exception:
                    pass
            
            # 2. Clear default icon if not explicitly set in the plugin class
            # This preserves the "clean" look for plugins that don't want an icon
            # unless they specifically override ICON or have a .png file.
            elif icon == "🔌" and "ICON" not in interface_class.__dict__:
                icon = ""
            
        popup = settings_popups.get(name)
        
        # If it's a new plugin without a custom popup, use add_sensor with pre-selection
        if not popup:
            # We use a captured 'name' variable in the lambda to ensure it calls with the right one
            popup = lambda n=name: self.sensor_controller.add_sensor(preselected_type=n)
            
        card, status_label = create_card(name, icon, popup, is_plugin=is_plugin)
        card.setProperty("is_plugin", is_plugin)
        # Ensure name is stored on card for status lookups
        card.setProperty("interface_name", name)
        
        # Add to grid layout (2 columns)
        row = i // 2
        col = i % 2
        devices_cards_layout.addWidget(card, row, col)
        
        # Keep references for updates
        self.interface_status_labels[name] = status_label
        
        # Also maintain legacy attribute names for backward compatibility with status update methods
        legacy_name_map = {
            "Serial": "other",
            "Read CSV": "csv"
        }
        attr_name = legacy_name_map.get(name, name.lower().replace(' ', '_'))
        legacy_attr = f"{attr_name}_status"
        setattr(self, legacy_attr, status_label)

    # Note: Remote DAQ will be added by StreamController at the end
    
    # --- ADDED: Outbound Interfaces Section ---
    outbound_interfaces = InterfaceRegistry.get_outbound_interfaces()
    if outbound_interfaces:
        # Get next available grid position
        start_idx = len(sorted_names)
        
        for i, (name, interface_class) in enumerate(outbound_interfaces.items()):
            idx = start_idx + i
            icon = getattr(interface_class, "ICON", "📤")
            
            # Outbound interfaces are always plugins
            is_plugin = True
            is_outbound = True
            
            # Handle icons for plugins (reusing logic)
            if icon and (icon.endswith(".png") or icon.endswith(".svg")):
                try:
                    import inspect
                    plugin_file = inspect.getfile(interface_class)
                    plugin_dir = os.path.dirname(plugin_file)
                    potential_path = os.path.join(plugin_dir, icon)
                    if os.path.exists(potential_path):
                        icon = potential_path
                except Exception: pass

            # Use create_card with is_outbound flag (we'll need to update create_card too)
            card, status_label = create_card(name, icon, None, is_plugin=True, is_outbound=True)
            card.setProperty("is_plugin", True)
            card.setProperty("is_outbound", True)
            card.setProperty("interface_name", name)
            
            # Connect outbound plugin toggle/configure
            def handle_outbound_click(n=name):
                if not hasattr(self, 'data_collection_controller'):
                    return
                
                dcc = self.data_collection_controller
                plugin = next((p for p in dcc.outbound_plugins if getattr(p, 'name', '') == n), None)
                
                if plugin:
                    # Always show settings dialog on click
                    from app.ui.dialogs.interface_config_dialog import InterfaceConfigDialog
                    cls = InterfaceRegistry.get_interface_class(n)
                    
                    # Load current settings from QSettings
                    settings_key = n.lower().replace(" ", "_")
                    current_config = {}
                    
                    # Load standard fields
                    current_config["auto_connect"] = self.settings.value(f"{settings_key}_auto_connect", "false") == "true"
                    current_config["enabled"] = self.settings.value(f"{settings_key}_enabled", "true") == "true"
                    
                    schema = getattr(cls, 'CONFIG_SCHEMA', {})
                    for field in schema:
                        val = self.settings.value(f"{settings_key}_{field}")
                        if val is not None:
                            current_config[field] = val
                    
                    dialog = InterfaceConfigDialog(self, interface_class=cls, interface_instance=plugin, config=current_config)
                    if dialog.exec():
                        # Save new config to QSettings
                        new_config = dialog.get_config()
                        # Standard fields
                        self.settings.setValue(f"{settings_key}_auto_connect", "true" if new_config.get("auto_connect") else "false")
                        self.settings.setValue(f"{settings_key}_enabled", "true" if new_config.get("enabled") else "false")
                        
                        # Schema fields
                        for field, val in new_config.items():
                            if field not in ["auto_connect", "enabled"]:
                                self.settings.setValue(f"{settings_key}_{field}", val)
                        
                        # If enabled and not connected, connect
                        if new_config.get("enabled") and not plugin.is_connected():
                            plugin.connect()
                    
                    self.update_status_indicators()

            card.mousePressEvent = lambda event, n=name: handle_outbound_click(n)

            row = idx // 2
            col = idx % 2
            devices_cards_layout.addWidget(card, row, col)
            self.interface_status_labels[name] = status_label
    # ------------------------------------------

    # Add stretch to grid to push cards to top
    devices_cards_layout.setRowStretch(devices_cards_layout.rowCount(), 1)
    
    # Wrap device cards in a scroll area to prevent height blocking
    devices_scroll = QScrollArea()
    devices_scroll.setWidgetResizable(True)
    devices_scroll.setFrameShape(QFrame.Shape.NoFrame)
    devices_scroll.setWidget(devices_cards_container)
    devices_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    
    # Store reference for StreamController to add Remote DAQ button
    self.devices_cards_layout = devices_cards_layout
    self.device_card_style = device_card_style
    self.device_card_size = (card_width, card_height)
    
    # Assembly of the sidebar
    devices_section_layout.addWidget(devices_scroll)
    
    # Ensure devices section expands to fill height
    devices_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    
    sidebar_layout.addWidget(devices_section)
    
    # Info text bottom layout to match right side
    sidebar_bottom_container = QWidget()
    sidebar_bottom_container.setFixedHeight(32) # Match height of help button on right
    sidebar_bottom_layout = QHBoxLayout(sidebar_bottom_container)
    sidebar_bottom_layout.setContentsMargins(0, 0, 0, 0)
    sidebar_bottom_layout.addWidget(custom_interface_info, alignment=Qt.AlignmentFlag.AlignVCenter)
    sidebar_bottom_layout.addStretch()
    
    sidebar_layout.addWidget(sidebar_bottom_container)
    
    # Set maximum width for sidebar to allow 2 columns of cards + info text
    sidebar_wrapper.setMaximumWidth(270)
    sidebar_wrapper.setMinimumWidth(0)
    
    # Add sidebar to horizontal splitter (left side)
    self.sensors_splitter.addWidget(sidebar_wrapper)
    
    # Sensor Management section - modernized (matching theme)
    # Wrap it in a container so we can put the help area below it on the right side only
    sensor_right_wrapper = QWidget()
    sensor_right_wrapper_layout = QVBoxLayout(sensor_right_wrapper)
    sensor_right_wrapper_layout.setContentsMargins(0, 0, 0, 0)
    sensor_right_wrapper_layout.setSpacing(10)

    sensor_container = QGroupBox("Sensor Management")
    sensor_container.setStyleSheet(GroupBoxStyles.default())
    sensor_container_layout = QVBoxLayout(sensor_container)
    sensor_container_layout.setContentsMargins(10, 10, 2, 10) # Reduced right margin from 10 to 2
    sensor_container_layout.setSpacing(10)
    
    # Sensor data table with modern styling
    self.data_table = QTableWidget(0, 7)
    self.data_table.setHorizontalHeaderLabels(["Use", "Sensor", "Value", "Interface", "Offset/Unit", "Color", "Cal."])
    self.data_table.horizontalHeader().setStretchLastSection(False)
    self.data_table.setColumnWidth(0, 45)
    self.data_table.setColumnWidth(1, 130)
    self.data_table.setColumnWidth(2, 90)
    self.data_table.setColumnWidth(3, 80)
    self.data_table.setColumnWidth(4, 90)
    self.data_table.setColumnWidth(5, 60)
    self.data_table.setColumnWidth(6, 45)
    
    # Modern table styling from theme
    self.data_table.setStyleSheet(TableStyles.default())
    
    # Allow table to fit within its container and scroll horizontally if needed
    self.data_table.setMinimumHeight(100) # Reduced from 200 to allow shrinking
    self.data_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    self.data_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    self.data_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self.data_table.setObjectName("data_table")
    self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    self.data_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    
    # Sensor buttons with modern styling from theme
    sensor_controls = QHBoxLayout()
    sensor_controls.setSpacing(8)
    
    sensor_btn_style = ButtonStyles.get("secondary", size="small")
    add_btn_style = ButtonStyles.get("success", size="small")
    remove_btn_style = ButtonStyles.get("danger", size="small")
    
    self.add_sensor_btn = QPushButton("➕ Add Sensor")
    self.add_sensor_btn.setObjectName("add_sensor_btn")
    self.add_sensor_btn.setStyleSheet(add_btn_style)
    self.add_sensor_btn.setFixedHeight(32)
    
    self.edit_sensor_btn = QPushButton("✏️ Edit")
    self.edit_sensor_btn.setObjectName("edit_sensor_btn")
    self.edit_sensor_btn.setStyleSheet(sensor_btn_style)
    self.edit_sensor_btn.setFixedHeight(32)
    
    self.remove_sensor_btn = QPushButton("🗑️ Remove")
    self.remove_sensor_btn.setObjectName("remove_sensor_btn")
    self.remove_sensor_btn.setStyleSheet(remove_btn_style)
    self.remove_sensor_btn.setFixedHeight(32)
    
    sensor_controls.addWidget(self.add_sensor_btn)
    sensor_controls.addWidget(self.edit_sensor_btn)
    sensor_controls.addWidget(self.remove_sensor_btn)
    sensor_controls.addStretch()
    
    sensor_container_layout.addLayout(sensor_controls)
    sensor_container_layout.addWidget(self.data_table)
    
    # Connect table events
    self.data_table.cellClicked.connect(self.select_sensor)
    self.data_table.cellDoubleClicked.connect(lambda row, col: self.sensor_controller.edit_sensor() if hasattr(self, 'sensor_controller') else None)
    
    sensor_right_wrapper_layout.addWidget(sensor_container)

    # Bottom row with help button - now moved inside the right wrapper
    sensors_bottom_layout = QHBoxLayout()
    
    # Explanation text
    explanation_label = QLabel("💡 'Use' checkbox controls visualization in graphs. All enabled sensors are recorded.")
    explanation_label.setStyleSheet("color: #666; font-size: 10px;")
    sensors_bottom_layout.addWidget(explanation_label)
    
    sensors_bottom_layout.addStretch()
    
    # Help button
    self.sensors_help_btn = QPushButton("❓ Help")
    self.sensors_help_btn.setCheckable(True)
    self.sensors_help_btn.setFixedSize(80, 32)
    self.sensors_help_btn.setStyleSheet(ButtonStyles.get("secondary", size="small"))
    sensors_bottom_layout.addWidget(self.sensors_help_btn)
    
    sensor_right_wrapper_layout.addLayout(sensors_bottom_layout)
    
    # Add sensor right wrapper to horizontal splitter (right side)
    self.sensors_splitter.addWidget(sensor_right_wrapper)
    
    # Set initial sizes for the sensors splitter (e.g., 270px for sidebar, remainder for table)
    self.sensors_splitter.setSizes([270, 1000])
    
    # Add horizontal splitter to main vertical layout
    sensors_main_layout.addWidget(self.sensors_splitter)
    
    # Add main container to layout
    sensors_layout.addWidget(sensors_main_container)
    
    # Right side: Help panel
    from app.ui.tools.help_panel import HelpPanel, get_help_content
    
    self.sensors_help_container = QWidget()
    self.sensors_help_container.setVisible(False)
    self.sensors_help_container.setFixedWidth(320)
    sensors_help_container_layout = QVBoxLayout(self.sensors_help_container)
    sensors_help_container_layout.setContentsMargins(0, 0, 0, 0)
    
    self.sensors_help_panel = HelpPanel("Sensors Help")
    sensors_help_container_layout.addWidget(self.sensors_help_panel)
    
    # Load sensors help content
    sensors_help_content = get_help_content("sensors")
    self.sensors_help_panel.clear_sections()
    for section in sensors_help_content.get("sections", []):
        self.sensors_help_panel.add_section(
            section.get("title", ""),
            section.get("content", ""),
            section.get("icon", "📖")
        )
    if self.sensors_help_panel.sections:
        self.sensors_help_panel.sections[0].expand()
    
    sensors_layout.addWidget(self.sensors_help_container)
    
    # Connect help button
    self.sensors_help_visible = False
    
    def toggle_sensors_help():
        self.sensors_help_visible = not self.sensors_help_visible
        self.sensors_help_container.setVisible(self.sensors_help_visible)
        self.sensors_help_btn.setChecked(self.sensors_help_visible)
    
    self.sensors_help_btn.clicked.connect(toggle_sensors_help)
    self.sensors_help_panel.close_requested.connect(toggle_sensors_help)
    
    # Create Graphs Tab
    graphs_tab = QWidget()
    self.graphs_tab = graphs_tab  # Store reference to avoid hardcoded indexing
    graphs_layout = QVBoxLayout(graphs_tab)
    graphs_layout.setContentsMargins(10, 0, 10, 0)
    
    # Create a splitter for the graphs tab
    graphs_splitter = QSplitter(Qt.Orientation.Horizontal)
    graphs_layout.addWidget(graphs_splitter)
    
    # Left side - Graph controls and info - wrapped in scroll area for small screens
    graph_controls_scroll = QScrollArea()
    graph_controls_scroll.setWidgetResizable(True)
    graph_controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
    graph_controls_scroll.setMinimumWidth(250)
    graph_controls_scroll.setMaximumWidth(400)
    # Only horizontal scrollbar when necessary for the graph controls
    graph_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    graph_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    
    graph_controls_widget = QWidget()
    graph_controls_widget.setObjectName("graph_controls_widget")
    # Set a minimum width to ensure horizontal scrollbar appears when shrunk
    graph_controls_widget.setMinimumWidth(280) 
    graph_controls_layout = QVBoxLayout(graph_controls_widget)
    graph_controls_layout.setContentsMargins(0, 0, 10, 0)
    graph_controls_widget.setMinimumHeight(100)
    
    graph_controls_scroll.setWidget(graph_controls_widget)
    
    # Graph type selection
    graph_type_group = QGroupBox("Graph Type")
    graph_type_group.setStyleSheet(GroupBoxStyles.default())
    graph_type_layout = QVBoxLayout(graph_type_group)
    
    graph_type_layout.addWidget(QLabel("Graph Type:"))
    self.graph_type_combo = QComboBox()
    self.graph_type_combo.addItems([
        "Standard Time Series", 
        "Temperature Difference", 
        "Rate of Change (dT/dt)", 
        "Moving Average",
        "Fourier Analysis",
        "Histogram",
        "Box Plot",
        "Correlation Analysis"
    ])
    graph_type_layout.addWidget(self.graph_type_combo)
    
    # Connect graph type combo to update UI elements and info text
    self.graph_type_combo.currentIndexChanged.connect(lambda: [
        self.update_graph_ui_elements(),
        update_graph_info(),
        self.update_graph()
    ])
    
    # Graph info area - compact description for selected type only
    graph_info_text = QLabel()
    graph_info_text.setWordWrap(True)
    graph_info_text.setMinimumHeight(40)
    graph_info_text.setMaximumHeight(60)
    graph_info_text.setStyleSheet(f"background-color: {COLORS.BG_CARD}; color: {COLORS.TEXT_SECONDARY}; border-radius: 5px; padding: 8px; font-size: 11px;")
    graph_info_text.setText("📊 Standard Time Series: Shows raw sensor values over time. Select multiple sensors to compare.")
    graph_type_layout.addWidget(graph_info_text)
    
    # Connect graph type combo to update info text
    def update_graph_info():
        graph_type = self.graph_type_combo.currentText()
        info_texts = {
            "Standard Time Series": "📊 Standard Time Series: Shows raw sensor values over time. Select multiple sensors to compare.",
            "Temperature Difference": "🔀 Temperature Difference: Shows T₁-T₂ over time. Useful for heat transfer analysis.",
            "Rate of Change (dT/dt)": "📈 Rate of Change: Shows how quickly values change. Identifies thermal response times.",
            "Moving Average": "〰️ Moving Average: Smooths fluctuations to reveal underlying trends.",
            "Fourier Analysis": "🎵 Fourier Analysis: Reveals periodic components and oscillations in frequency domain.",
            "Histogram": "📊 Histogram: Shows value distribution - how often each value occurs.",
            "Box Plot": "📦 Box Plot: Statistical summary with median, quartiles, and outliers.",
            "Correlation Analysis": "🔗 Correlation: Shows relationship strength between two sensors."
        }
        graph_info_text.setText(info_texts.get(graph_type, "Select a graph type for description."))
    
    self.graph_type_combo.currentIndexChanged.connect(update_graph_info)
    
    # Sensor selection
    sensor_selection_group = QGroupBox("Sensor Selection")
    sensor_selection_group.setStyleSheet(GroupBoxStyles.default())
    sensor_selection_layout = QVBoxLayout(sensor_selection_group)
    
    # Primary sensor
    primary_sensor_layout = QHBoxLayout()
    primary_sensor_layout.addWidget(QLabel("Primary Sensor:"))
    self.graph_primary_sensor = QComboBox()
    self.graph_primary_sensor.currentIndexChanged.connect(self.update_graph)
    primary_sensor_layout.addWidget(self.graph_primary_sensor)
    sensor_selection_layout.addLayout(primary_sensor_layout)
    
    # Multi-sensor selection for Standard Time Series
    self.multi_sensor_group = QGroupBox("Additional Sensors (for Standard Time Series)")
    self.multi_sensor_group.setStyleSheet(GroupBoxStyles.subtle())
    multi_sensor_layout = QVBoxLayout(self.multi_sensor_group)
    self.multi_sensor_list = QListWidget()
    self.multi_sensor_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
    self.multi_sensor_list.itemSelectionChanged.connect(self.update_graph)
    multi_sensor_layout.addWidget(self.multi_sensor_list)
    sensor_selection_layout.addWidget(self.multi_sensor_group)
    
    # Secondary sensor (for difference and correlation)
    secondary_sensor_layout = QHBoxLayout()
    self.secondary_sensor_label = QLabel("Secondary Sensor:")
    self.secondary_sensor_label.setObjectName("secondary_sensor_label")
    secondary_sensor_layout.addWidget(self.secondary_sensor_label)
    self.graph_secondary_sensor = QComboBox()
    self.graph_secondary_sensor.currentIndexChanged.connect(self.update_graph)
    secondary_sensor_layout.addWidget(self.graph_secondary_sensor)
    sensor_selection_layout.addLayout(secondary_sensor_layout)
    
    # Graph parameters
    graph_params_group = QGroupBox("Graph Parameters")
    graph_params_group.setStyleSheet(GroupBoxStyles.default())
    graph_params_layout = QGridLayout(graph_params_group)
    
    # Timespan
    graph_params_layout.addWidget(QLabel("Timespan:"), 0, 0)
    self.graph_timespan = QComboBox()
    self.graph_timespan.addItems(["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"])
    self.graph_timespan.setCurrentText("All")  # Default to All
    graph_params_layout.addWidget(self.graph_timespan, 0, 1)
    
    # Window size for moving average
    self.window_size_label = QLabel("Window Size:")
    self.window_size_label.setObjectName("window_size_label")
    graph_params_layout.addWidget(self.window_size_label, 1, 0)
    self.window_size_spinbox = QSpinBox()
    self.window_size_spinbox.setRange(2, 100)
    self.window_size_spinbox.setValue(10)
    self.window_size_spinbox.setSuffix(" points")
    self.window_size_spinbox.valueChanged.connect(self.update_graph)
    graph_params_layout.addWidget(self.window_size_spinbox, 1, 1)
    
    # Number of bins for histogram
    self.graph_histogram_bins_label = QLabel("Histogram Bins:")
    self.graph_histogram_bins_label.setObjectName("graph_histogram_bins_label")
    graph_params_layout.addWidget(self.graph_histogram_bins_label, 2, 0)
    self.histogram_bins_spinbox = QSpinBox()
    self.histogram_bins_spinbox.setRange(5, 100)
    self.histogram_bins_spinbox.setValue(20)
    self.histogram_bins_spinbox.valueChanged.connect(self.update_graph)
    graph_params_layout.addWidget(self.histogram_bins_spinbox, 2, 1)
    
    # Live Update Checkbox
    self.graph_live_update_checkbox = QCheckBox("Live Update")
    self.graph_live_update_checkbox.setToolTip("Check to update graph periodically with live data during a run")
    self.graph_live_update_checkbox.setChecked(True)  # Checked by default
    # Add checkbox to layout, spanning 2 columns for better spacing
    graph_params_layout.addWidget(self.graph_live_update_checkbox, 3, 0, 1, 2)
    
    # Control Run Section
    control_run_label = QLabel("Control Run:")
    graph_params_layout.addWidget(control_run_label, 4, 0)
    
    self.control_run_selector = QComboBox()
    self.control_run_selector.setToolTip("Select a run to use as control data for comparison")
    self.control_run_selector.addItem("None")
    # The controller will populate this with available runs
    self.control_run_selector.setMinimumWidth(200)
    graph_params_layout.addWidget(self.control_run_selector, 4, 1)
    
    # Control Run Time Offset
    time_offset_label = QLabel("Time Offset (s):")
    graph_params_layout.addWidget(time_offset_label, 5, 0)
    
    self.control_run_time_offset = QDoubleSpinBox()
    self.control_run_time_offset.setRange(-3600.0, 3600.0)  # +/- 1 hour
    self.control_run_time_offset.setValue(0.0)
    self.control_run_time_offset.setDecimals(2)
    self.control_run_time_offset.setSingleStep(1.0)
    self.control_run_time_offset.setSuffix(" s")
    self.control_run_time_offset.setToolTip("Adjust the start time of the control run data (positive = shift right, negative = shift left)")
    graph_params_layout.addWidget(self.control_run_time_offset, 5, 1)
    
    # Show Control Run Checkbox
    self.show_control_run_checkbox = QCheckBox("Show Control Run")
    self.show_control_run_checkbox.setToolTip("Check to display control run data on the graph")
    self.show_control_run_checkbox.setChecked(False)  # Unchecked by default
    # Connect the checkbox to update sensor lists and graph when toggled
    self.show_control_run_checkbox.stateChanged.connect(self.on_show_control_run_changed)
    # Add checkbox to layout, spanning 2 columns for better spacing
    graph_params_layout.addWidget(self.show_control_run_checkbox, 6, 0, 1, 2)

    # Show automation markers checkbox
    self.show_automation_events_checkbox = QCheckBox("Show Automation Events")
    self.show_automation_events_checkbox.setToolTip("Toggle automation trigger/action markers on graphs")
    self.show_automation_events_checkbox.setChecked(True)
    self.show_automation_events_checkbox.stateChanged.connect(self.on_show_automation_markers_changed)
    graph_params_layout.addWidget(self.show_automation_events_checkbox, 7, 0, 1, 2)
    
    # Plot Format Settings
    plot_format_group = QGroupBox("Plot Format")
    plot_format_group.setStyleSheet(GroupBoxStyles.default())
    plot_format_layout = QGridLayout(plot_format_group)
    
    # Style presets
    plot_format_layout.addWidget(QLabel("Style Preset:"), 0, 0)
    self.plot_style_preset = QComboBox()
    self.plot_style_preset.addItems([
        "Standard", 
        "Solarized", 
        "Dark", 
        "High Contrast", 
        "Pastel",
        "Colorful"
    ])
    # Style preset will be set by load_settings method
    self.plot_style_preset.setCurrentIndex(3)  # Default to "High Contrast" (index 3)
    
    # Graph Simplification (Downsampling)
    self.graph_downsampling_checkbox = QCheckBox("Enable Graph Simplification")
    self.graph_downsampling_checkbox.setToolTip("Reduces data points displayed on graphs for better performance. Disable to see every detail.")
    
    # Use SettingsModel for safer boolean retrieval if available
    is_downsampling_enabled = True
    if hasattr(self, 'settings_model'):
        is_downsampling_enabled = self.settings_model.get_bool("graph_downsampling", True)
    else:
        is_downsampling_enabled = self.settings.value("graph_downsampling", "true") == "true"
        
    self.graph_downsampling_checkbox.setChecked(is_downsampling_enabled)
    
    # Connect to save setting and then update graph
    def on_downsampling_toggled(state):
        enabled = (state == Qt.CheckState.Checked.value)
        if hasattr(self, 'settings_model'):
            self.settings_model.set_value("graph_downsampling", enabled)
        else:
            self.settings.setValue("graph_downsampling", "true" if enabled else "false")
        self.apply_plot_formatting()
        self.update_graph()
    self.graph_downsampling_checkbox.stateChanged.connect(on_downsampling_toggled)
    plot_format_layout.addWidget(self.graph_downsampling_checkbox, 1, 0, 1, 2)
    
    # Connect to the apply_plot_formatting function and then update graphs
    self.plot_style_preset.currentIndexChanged.connect(lambda: [
        self.apply_plot_formatting(),
        self.update_graph(),
        self.update_dashboard_graph() if hasattr(self, 'dashboard_graph_widget') else None
    ])
    
    plot_format_layout.addWidget(self.plot_style_preset, 0, 1)
    
    # Font size
    plot_format_layout.addWidget(QLabel("Font Size:"), 2, 0)
    self.plot_font_size = QSpinBox()
    self.plot_font_size.setRange(8, 24)
    self.plot_font_size.setValue(10)
    self.plot_font_size.setSuffix(" pt")
    
    # Connect to the apply_plot_formatting function and then update graphs
    self.plot_font_size.valueChanged.connect(lambda: [
        self.apply_plot_formatting(),
        self.update_graph(),
        self.update_dashboard_graph() if hasattr(self, 'dashboard_graph_widget') else None
    ])
    
    plot_format_layout.addWidget(self.plot_font_size, 2, 1)
    
    # Line size
    plot_format_layout.addWidget(QLabel("Line Width:"), 3, 0)
    self.plot_line_width = QSpinBox()
    self.plot_line_width.setRange(1, 10)
    self.plot_line_width.setValue(2)  # Will be overridden by load_settings
    self.plot_line_width.setSuffix(" px")
    
    # Connect to the apply_plot_formatting function and then update graphs
    self.plot_line_width.valueChanged.connect(lambda: [
        self.apply_plot_formatting(),
        self.update_graph(),
        self.update_dashboard_graph() if hasattr(self, 'dashboard_graph_widget') else None
    ])
    
    plot_format_layout.addWidget(self.plot_line_width, 3, 1)
    
    # Add all controls to the layout
    graph_controls_layout.addWidget(graph_type_group)
    graph_controls_layout.addWidget(sensor_selection_group)
    graph_controls_layout.addWidget(graph_params_group)
    graph_controls_layout.addWidget(plot_format_group)
    graph_controls_layout.addStretch()
    
    # Initialize UI element visibility based on default graph type
    self.update_graph_ui_elements()
    
    # Right side - Graph display
    graph_display_widget = QWidget()
    graph_display_layout = QVBoxLayout(graph_display_widget)
    
    # Main graph
    self.graph_widget = pyqtgraph.PlotWidget()
    # Apply dark theme settings
    # Apply dark theme to main graph
    GraphStyles.apply_dark_theme(self.graph_widget)
    self.graph_widget.setLabel('left', 'Value')
    self.graph_widget.setLabel('bottom', 'Sample Count')
    self.graph_widget.addLegend()
    graph_display_layout.addWidget(self.graph_widget)
    
    # Add widgets to splitter
    graphs_splitter.addWidget(graph_controls_scroll)
    graphs_splitter.addWidget(graph_display_widget)
    graphs_splitter.setSizes([400, 800])  # Initial sizes
    
    # Create Automation Tab
    automation_tab = QWidget()
    self.automation_tab = automation_tab
    automation_layout = QHBoxLayout(automation_tab)
    automation_layout.setContentsMargins(10, 0, 10, 0)
    automation_layout.setSpacing(10)
    
    # Quick Templates Box
    predefined_group = QGroupBox("Quick Templates")
    predefined_group.setFixedWidth(220)
    predefined_group.setStyleSheet(GroupBoxStyles.default())
    predefined_layout = QVBoxLayout(predefined_group)
    
    predefined_label = QLabel("Double-click to load template:")
    predefined_label.setStyleSheet(f"font-size: 11px; color: {COLORS.TEXT_SECONDARY}; margin-bottom: 5px;")
    predefined_layout.addWidget(predefined_label)
    
    self.predefined_list = QListWidget()
    self.predefined_list.setStyleSheet(f"""
        QListWidget {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QListWidget::item {{
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid {COLORS.BORDER_DEFAULT};
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 8px;
            color: {COLORS.TEXT_PRIMARY};
        }}
        QListWidget::item:hover {{
            background-color: rgba(255, 255, 255, 0.1);
            border-color: {COLORS.PRIMARY};
        }}
        QListWidget::item:selected {{
            background-color: {COLORS.PRIMARY}33;
            border-color: {COLORS.PRIMARY};
            color: white;
        }}
    """)
    predefined_layout.addWidget(self.predefined_list)
    automation_layout.addWidget(predefined_group)
    
    # Main content container (restored fixed width)
    automation_main_container = QFrame()
    automation_main_container.setFixedWidth(700)
    automation_main_container.setStyleSheet(f"""
        QFrame {{
            background-color: {COLORS.BG_DARK};
            border: 1px solid {COLORS.BORDER_DEFAULT};
            border-radius: 8px;
        }}
    """)
    automation_main_layout = QVBoxLayout(automation_main_container)
    automation_main_layout.setContentsMargins(10, 10, 10, 10)
    automation_main_layout.setSpacing(10)
    
    # Automation sequences section
    automation_sequences_group = QGroupBox("Automation Sequences")
    automation_sequences_group.setStyleSheet(GroupBoxStyles.default())
    automation_sequences_group.setMinimumHeight(100) # Allow vertical shrinking
    automation_sequences_layout = QVBoxLayout(automation_sequences_group)
    automation_sequences_layout.setContentsMargins(10, 10, 10, 10)
    
    # Table to display defined automation sequences
    self.sequences_table = QTableWidget()
    self.sequences_table.setColumnCount(3)
    self.sequences_table.setHorizontalHeaderLabels(["Name", "Status", "Actions"])
    self.sequences_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    self.sequences_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.sequences_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.sequences_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.sequences_table.setMinimumHeight(100) # Reduced from 200 to allow shrinking
    automation_sequences_layout.addWidget(self.sequences_table)
    
    # Sequence control buttons
    sequence_buttons_layout = QHBoxLayout()
    
    self.add_sequence_btn = QPushButton("New Sequence")
    self.add_sequence_btn.setStyleSheet(green_button_style)  # Apply green button style to New Sequence button
    self.edit_sequence_btn = QPushButton("Edit Sequence")
    self.remove_sequence_btn = QPushButton("Delete Sequence")
    self.start_sequence_btn = QPushButton("Run Sequence")
    self.stop_sequence_btn = QPushButton("Stop Sequence")
    
    sequence_buttons_layout.addWidget(self.add_sequence_btn)
    sequence_buttons_layout.addWidget(self.edit_sequence_btn)
    sequence_buttons_layout.addWidget(self.remove_sequence_btn)
    sequence_buttons_layout.addWidget(self.start_sequence_btn)
    sequence_buttons_layout.addWidget(self.stop_sequence_btn)
    
    automation_sequences_layout.addLayout(sequence_buttons_layout)
    
    # Error notification label (hidden by default)
    self.automation_error_label = QLabel("")
    self.automation_error_label.setWordWrap(True)
    self.automation_error_label.setStyleSheet("""
        QLabel {
            color: #ff4444;
            background-color: rgba(255, 68, 68, 0.15);
            border: 1px solid #ff4444;
            border-radius: 4px;
            padding: 8px 12px;
            font-weight: bold;
            font-size: 12px;
        }
    """)
    self.automation_error_label.setVisible(False)
    automation_sequences_layout.addWidget(self.automation_error_label)
    
    automation_main_layout.addWidget(automation_sequences_group)
    
    # Time-lapse Video Creation section
    timelapse_group = QGroupBox("Time-lapse Video Creation")
    timelapse_group.setStyleSheet(GroupBoxStyles.default())
    timelapse_layout = QVBoxLayout(timelapse_group)
    
    # Description
    timelapse_description = QLabel("Create time-lapse videos from snapshots in the media folder.")
    timelapse_description.setWordWrap(True)
    timelapse_layout.addWidget(timelapse_description)
    
    # Hidden fields for storing values (not visible in UI)
    self.timelapse_source_folder = QLineEdit()
    self.timelapse_output_file = QLineEdit()
    self.timelapse_duration = QSpinBox()
    self.timelapse_duration.setRange(1, 300)
    self.timelapse_duration.setValue(30)
    self.timelapse_fps = QSpinBox()
    self.timelapse_fps.setRange(10, 60)
    self.timelapse_fps.setValue(30)
    self.timelapse_format = QComboBox()
    self.timelapse_format.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"])
    self.timelapse_browse_btn = QPushButton()
    self.timelapse_output_browse_btn = QPushButton()
    
    # Create button
    self.create_timelapse_btn = QPushButton("Create Time-lapse Video")
    self.create_timelapse_btn.setMinimumHeight(40)
    timelapse_layout.addWidget(self.create_timelapse_btn)
    
    # Add timelapse group to the automation content
    automation_main_layout.addWidget(timelapse_group)
    
    # Bottom row with help button
    automation_bottom_layout = QHBoxLayout()
    automation_bottom_layout.addStretch()
    
    # Help button
    self.automation_help_btn = QPushButton("❓ Help")
    self.automation_help_btn.setCheckable(True)
    self.automation_help_btn.setFixedSize(80, 32)
    self.automation_help_btn.setStyleSheet(ButtonStyles.get("secondary", size="small"))
    automation_bottom_layout.addWidget(self.automation_help_btn)
    
    automation_main_layout.addLayout(automation_bottom_layout)
    
    # Add main container to layout
    automation_layout.addWidget(automation_main_container)
    
    # Right side: Help panel (import HelpPanel and get_help_content)
    from app.ui.tools.help_panel import HelpPanel, get_help_content
    
    # Create a container for the help panel to match height
    self.automation_help_container = QWidget()
    self.automation_help_container.setVisible(False)
    self.automation_help_container.setFixedWidth(320)
    automation_help_container_layout = QVBoxLayout(self.automation_help_container)
    automation_help_container_layout.setContentsMargins(0, 0, 0, 0)
    
    self.automation_help_panel = HelpPanel("Automation Help")
    automation_help_container_layout.addWidget(self.automation_help_panel)
    
    # Load automation help content
    automation_help_content = get_help_content("automation")
    self.automation_help_panel.clear_sections()
    for section in automation_help_content.get("sections", []):
        self.automation_help_panel.add_section(
            section.get("title", ""),
            section.get("content", ""),
            section.get("icon", "📖")
        )
    # Expand first section by default
    if self.automation_help_panel.sections:
        self.automation_help_panel.sections[0].expand()
    
    # Add help container to layout
    automation_layout.addWidget(self.automation_help_container)
    
    # Connect help button and panel close
    self.automation_help_visible = False
    
    def toggle_automation_help():
        self.automation_help_visible = not self.automation_help_visible
        self.automation_help_container.setVisible(self.automation_help_visible)
        self.automation_help_btn.setChecked(self.automation_help_visible)
    
    self.automation_help_btn.clicked.connect(toggle_automation_help)
    self.automation_help_panel.close_requested.connect(toggle_automation_help)
    
    # Center spacer right
    automation_layout.addStretch()
    
    # Create Settings Tab
    settings_tab = QWidget()
    self.settings_tab = settings_tab
    settings_layout = QVBoxLayout(settings_tab)
    
    # Create a horizontal layout for the two columns with less spacing
    settings_columns_layout = QHBoxLayout()
    settings_columns_layout.setSpacing(20)  # Reduce spacing between columns
    settings_columns_layout.setContentsMargins(20, 10, 20, 10)  # Reduced vertical padding
    
    # Create left column layout
    left_column_layout = QVBoxLayout()
    left_column_layout.setSpacing(10)  # Reduce spacing between widgets
    
    # Create right column layout
    right_column_layout = QVBoxLayout()
    right_column_layout.setSpacing(10)  # Reduce spacing between widgets
    
    # Create hidden Arduino-related elements that are needed for the popup
    # These variables are referenced by other parts of the code
    self.arduino_port = QComboBox()
    self.arduino_port.setEditable(True)
    self.arduino_port.addItem(self.settings.value("arduino_port", "COM3"))
    self.arduino_port.setVisible(False)
    
    self.arduino_baud = QComboBox()
    self.arduino_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
    self.arduino_baud.setCurrentText(str(self.settings.value("arduino_baud", "9600")))
    self.arduino_baud.setVisible(False)
    
    self.arduino_poll_interval = QDoubleSpinBox()
    self.arduino_poll_interval.setRange(0.1, 60.0)
    self.arduino_poll_interval.setSingleStep(0.1)
    
    val = self.settings.value("arduino_poll_interval", "1.0")
    try:
        if val is not None and str(val).lower() != 'none':
            self.arduino_poll_interval.setValue(float(val))
        else:
            self.arduino_poll_interval.setValue(1.0)
    except (ValueError, TypeError):
        self.arduino_poll_interval.setValue(1.0)
    self.arduino_poll_interval.setVisible(False)
    
    self.arduino_connect_btn = QPushButton("Connect")
    self.arduino_connect_btn.setVisible(False)
    
    # Apply green border style for connect button
    green_border_style = """
        QPushButton {
            background-color: transparent;
            color: #4CAF50;
            border: 2px solid #4CAF50;
            padding: 6px 12px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: rgba(76, 175, 80, 0.1);
        }
        QPushButton:pressed {
            background-color: rgba(76, 175, 80, 0.2);
        }
    """
    self.arduino_connect_btn.setStyleSheet(green_border_style)
    
    self.arduino_detect_btn = QPushButton("Auto Detect")
    self.arduino_detect_btn.setVisible(False)
    
    # Command related elements
    self.arduino_command_type = QComboBox()
    self.arduino_command_type.addItems(["LED", "RELAY", "MOTOR", "SERVO", "CUSTOM"])
    self.arduino_command_type.setVisible(False)
    
    self.arduino_device_id = QLineEdit("1") 
    self.arduino_device_id.setVisible(False)
    
    self.arduino_command_value = QLineEdit("ON")
    self.arduino_command_value.setVisible(False)
    
    self.arduino_custom_command_label = QLabel("Custom:")
    self.arduino_custom_command_label.setVisible(False)
    
    self.arduino_custom_command = QLineEdit("")
    self.arduino_custom_command.setPlaceholderText("command:device=value;")
    self.arduino_custom_command.setVisible(False)
    
    self.arduino_send_command_btn = QPushButton("Send Command")
    self.arduino_send_command_btn.clicked.connect(self.send_arduino_command)
    self.arduino_send_command_btn.setVisible(False)
    
    # Connect handlers
    self.arduino_command_type.currentIndexChanged.connect(self.update_command_ui)
    self.arduino_detect_btn.clicked.connect(self.detect_arduino)
    self.arduino_connect_btn.clicked.connect(self.connect_arduino)
    
    # Add the hidden elements to a container to keep them in the UI layout
    hidden_elements_container = QWidget()
    hidden_elements_container.setVisible(False)
    hidden_layout = QVBoxLayout(hidden_elements_container)
    hidden_layout.addWidget(self.arduino_port)
    hidden_layout.addWidget(self.arduino_baud)
    hidden_layout.addWidget(self.arduino_poll_interval)
    hidden_layout.addWidget(self.arduino_connect_btn)
    hidden_layout.addWidget(self.arduino_detect_btn)
    hidden_layout.addWidget(self.arduino_command_type)
    hidden_layout.addWidget(self.arduino_device_id)
    hidden_layout.addWidget(self.arduino_command_value)
    hidden_layout.addWidget(self.arduino_custom_command_label)
    hidden_layout.addWidget(self.arduino_custom_command)
    hidden_layout.addWidget(self.arduino_send_command_btn)
    
    # Add the hidden container to the layout (it won't be visible)
    left_column_layout.addWidget(hidden_elements_container)
    
    # Create LabJack UI controls as attributes but don't show them in the UI
    self.labjack_type = QComboBox()
    self.labjack_type.addItems(["U3", "U6", "T7", "UE9"])
    self.labjack_type.setCurrentText(self.settings.value("labjack_type", "U3"))
    hidden_layout.addWidget(self.labjack_type)
    
    self.labjack_connect_btn = QPushButton("Connect")
    # Apply green border style for connect button
    self.labjack_connect_btn.setStyleSheet(green_border_style)
    hidden_layout.addWidget(self.labjack_connect_btn)
    
    self.labjack_test_btn = QPushButton("Test")
    hidden_layout.addWidget(self.labjack_test_btn)
    
    # Create hidden NDI settings elements (needed for code references)
    self.enable_ndi = QCheckBox("Enable NDI Output")
    self.enable_ndi.setChecked(self.settings.value("enable_ndi", "false") == "true")
    hidden_layout.addWidget(self.enable_ndi)
    
    self.ndi_source_name = QLineEdit(self.settings.value("ndi_source_name", "Artefakt DAQ"))
    hidden_layout.addWidget(self.ndi_source_name)
    
    self.ndi_with_overlays = QCheckBox("Include overlays in NDI output")
    self.ndi_with_overlays.setChecked(self.settings.value("ndi_with_overlays", "true") == "true")
    hidden_layout.addWidget(self.ndi_with_overlays)
    
    # NDI Settings - Removed as it's now in camera settings popup
    
    # Add stretch to push everything to the top
    left_column_layout.addStretch()
    
    # Camera Settings Section is being removed since it's now in a popup dialog
    
    # Add the columns to the horizontal layout
    settings_columns_layout.addLayout(left_column_layout)
    settings_columns_layout.addLayout(right_column_layout)
    
    # Add the columns layout to the main settings layout
    settings_layout.addLayout(settings_columns_layout)
    
    # Add Projects Tab
    projects_tab = QWidget()
    self.projects_tab = projects_tab
    projects_tab.setObjectName("projects_tab")
    projects_layout = QVBoxLayout(projects_tab)
    
    # Create a container for project content - no fixed minimum width to allow full compression
    project_container = QWidget()
    project_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)  # Allow expansion
    project_container_layout = QVBoxLayout(project_container)
    project_container_layout.setContentsMargins(10, 0, 10, 0)  # Removed top/bottom margins
    project_container_layout.setSpacing(8)  # Reduced spacing
    
    # Add container to tab with stretch factor to fill space
    projects_layout.addWidget(project_container, 1)
    
    # Modern hero section at the top
    hero_section = QFrame()
    hero_section.setStyleSheet("""
        QFrame {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #1a1a3a, stop:0.5 #2a2a5a, stop:1 #1a1a3a);
            border-radius: 8px;
            border: 1px solid #3a3a6a;
        }
    """)
    hero_layout = QHBoxLayout(hero_section)
    hero_layout.setContentsMargins(15, 8, 15, 8) # Reduced margins
    hero_layout.setSpacing(15)
    hero_section.setFixedHeight(60) # Compact fixed height
    
    # Icon/logo area
    hero_icon = QLabel("📁")
    hero_icon.setStyleSheet("font-size: 36px; background: transparent; border: none;")
    hero_layout.addWidget(hero_icon)
    
    # Text area
    hero_text_layout = QVBoxLayout()
    hero_text_layout.setSpacing(4)
    hero_title = QLabel("Project Management")
    hero_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff; background: transparent; border: none;")
    hero_text_layout.addWidget(hero_title)
    hero_subtitle = QLabel("Create and organize your data collection projects • Each run saves data, settings & timestamps")
    hero_subtitle.setStyleSheet("font-size: 12px; color: #aaa; background: transparent; border: none;")
    hero_text_layout.addWidget(hero_subtitle)
    hero_layout.addLayout(hero_text_layout)
    
    hero_layout.addStretch()
    
    # Help button in hero section
    self.project_help_btn = QPushButton("❓ Help")
    self.project_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.project_help_btn.setStyleSheet(ButtonStyles.get("secondary", "small"))
    self.project_help_btn.setFixedWidth(80)
    hero_layout.addWidget(self.project_help_btn)
    
    project_container_layout.addWidget(hero_section)
    
    # Create a horizontal splitter for the main content (replaces QHBoxLayout)
    self.projects_splitter = QSplitter(Qt.Orientation.Horizontal)
    self.projects_splitter.setChildrenCollapsible(False) # Prevent hiding columns completely
    self.projects_splitter.setHandleWidth(2)
    self.projects_splitter.setStyleSheet(f"""
        QSplitter::handle {{
            background-color: {COLORS.BORDER_DEFAULT};
        }}
        QSplitter::handle:hover {{
            background-color: {COLORS.PRIMARY};
        }}
    """)
    
    # Left column for project structure - wrapped in scroll area for small screens
    left_scroll_area = QScrollArea()
    left_scroll_area.setWidgetResizable(True)
    left_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    # Remove stylesheet that was forcing transparency on children
    
    left_column_widget = QWidget()
    left_column_widget.setObjectName("left_column_widget")
    # Explicitly apply input styles to ensure fields remain visible inside the scroll area
    left_column_widget.setStyleSheet(InputStyles.default())
    left_column_layout = QVBoxLayout(left_column_widget)
    left_column_layout.setContentsMargins(0, 0, 10, 0) # Small right margin for scrollbar
    left_column_layout.setSpacing(15)  # Increased spacing
    
    left_scroll_area.setWidget(left_column_widget)
    
    # Project section (directly in left column, no outer groupbox)
    project_group = QGroupBox("📁 Project")
    project_group_layout = QVBoxLayout(project_group)
    project_group_layout.setSpacing(8)
    project_group_layout.setContentsMargins(10, 10, 10, 10)
    
    # Store reference to the group box in the main window
    self.project_group = project_group
    
    # Set slightly larger font for groups
    sub_font = project_group.font()
    sub_font.setPointSize(11)
    sub_font.setBold(True)
    project_group.setFont(sub_font)
    
    # Apply modern theme style (dynamic status will be set via controller)
    project_group.setStyleSheet(GroupBoxStyles.with_status("warning"))
    
    # Project base directory
    base_dir_layout = QHBoxLayout()
    base_dir_layout.setSpacing(8)
    base_dir_label = QLabel("Base Directory:")
    base_dir_label.setMinimumWidth(100)
    base_dir_layout.addWidget(base_dir_label)
    self.project_base_dir = QLineEdit()
    self.project_base_dir.setPlaceholderText("Select a base directory for all projects")
    base_dir_layout.addWidget(self.project_base_dir, 1)
    self.browse_base_dir_btn = QPushButton("Browse...")
    base_dir_layout.addWidget(self.browse_base_dir_btn)
    project_group_layout.addLayout(base_dir_layout)
    
    # Project selection
    project_selection_layout = QHBoxLayout()
    project_selection_layout.setSpacing(8)
    project_label = QLabel("Name:")
    project_label.setMinimumWidth(100)
    project_selection_layout.addWidget(project_label)
    self.project_selector = QComboBox()
    self.project_selector.setEditable(True)
    self.project_selector.setPlaceholderText("Select or create a project")
    project_selection_layout.addWidget(self.project_selector, 1)
    self.new_project_btn = QPushButton("New")
    self.new_project_btn.setFixedWidth(80)
    project_selection_layout.addWidget(self.new_project_btn)
    project_group_layout.addLayout(project_selection_layout)
    
    # Project description
    project_desc_layout = QVBoxLayout()
    project_desc_label = QLabel("Description:")
    project_desc_label.setFixedHeight(20) # Fixed height to prevent label stretching
    project_desc_layout.addWidget(project_desc_label)
    self.project_description = QTextEdit()
    self.project_description.setMinimumHeight(60)
    self.project_description.setPlaceholderText("Enter a description for this project")
    project_desc_layout.addWidget(self.project_description, 1) # Allow to grow
    project_group_layout.addLayout(project_desc_layout, 1) # Description takes extra space
    
    # Add project group directly to left column
    left_column_layout.addWidget(project_group)
    
    # Test Series section
    test_series_group = QGroupBox("📋 Test Series")
    test_series_group_layout = QVBoxLayout(test_series_group)
    test_series_group_layout.setSpacing(8)
    test_series_group_layout.setContentsMargins(10, 10, 10, 10)
    
    # Store reference to the group box in the main window
    self.test_series_group = test_series_group
    
    # Set slightly larger font for groups
    test_series_group.setFont(sub_font)  # Reuse the same font
    
    # Apply modern theme style (dynamic status will be set via controller)
    test_series_group.setStyleSheet(GroupBoxStyles.with_status("warning"))
    
    # Test series selection
    test_series_layout = QHBoxLayout()
    test_series_layout.setSpacing(8)
    test_series_label = QLabel("Name:")
    test_series_label.setMinimumWidth(100)
    test_series_layout.addWidget(test_series_label)
    self.test_series_selector = QComboBox()
    self.test_series_selector.setEditable(True)
    self.test_series_selector.setPlaceholderText("Select or create a test series")
    test_series_layout.addWidget(self.test_series_selector, 1)
    self.new_test_series_btn = QPushButton("New")
    self.new_test_series_btn.setFixedWidth(80)
    test_series_layout.addWidget(self.new_test_series_btn)
    test_series_group_layout.addLayout(test_series_layout)
    
    # Test series description
    test_series_desc_layout = QVBoxLayout()
    test_series_desc_label = QLabel("Description:")
    test_series_desc_label.setFixedHeight(20) # Fixed height to prevent label stretching
    test_series_desc_layout.addWidget(test_series_desc_label)
    self.test_series_description = QTextEdit()
    self.test_series_description.setMinimumHeight(60)
    self.test_series_description.setPlaceholderText("Enter a description for this test series")
    test_series_desc_layout.addWidget(self.test_series_description, 1) # Allow to grow
    test_series_group_layout.addLayout(test_series_desc_layout, 1) # Description takes extra space
    
    # Add test series group directly to left column
    left_column_layout.addWidget(test_series_group)
    
    # Run section
    run_group = QGroupBox("▶️ Run")
    run_group_layout = QVBoxLayout(run_group)
    run_group_layout.setSpacing(8)
    run_group_layout.setContentsMargins(10, 10, 10, 10)
    
    # Store reference to the group box in the main window
    self.run_group = run_group
    
    # Set slightly larger font for groups
    run_group.setFont(sub_font)  # Reuse the same font
    
    # Apply modern theme style (dynamic status will be set via controller)
    run_group.setStyleSheet(GroupBoxStyles.with_status("warning"))
    
    # Sampling rate setting
    sampling_rate_layout = QHBoxLayout()
    sampling_rate_layout.setSpacing(8)
    sampling_rate_label = QLabel("Sampling Rate:")
    sampling_rate_label.setMinimumWidth(100)
    sampling_rate_layout.addWidget(sampling_rate_label)
    
    self.sampling_rate_spinbox = QDoubleSpinBox()
    self.sampling_rate_spinbox.setRange(0.1, 1000)
    self.sampling_rate_spinbox.setValue(1.0)  # Default 1.0 Hz
    self.sampling_rate_spinbox.setDecimals(2)
    self.sampling_rate_spinbox.setSingleStep(0.5)
    self.sampling_rate_spinbox.setToolTip("Global sampling rate for all sensors (Hz)")
    sampling_rate_layout.addWidget(self.sampling_rate_spinbox)
    
    sampling_rate_unit = QLabel("Hz")
    sampling_rate_layout.addWidget(sampling_rate_unit)
    sampling_rate_layout.addStretch(1)  # Add stretch to push controls to the left
    
    run_group_layout.addLayout(sampling_rate_layout)
    
    # Testers field
    testers_layout = QHBoxLayout()
    testers_layout.setSpacing(8)
    testers_label = QLabel("Testers:")
    testers_label.setMinimumWidth(100)
    testers_layout.addWidget(testers_label)
    
    self.run_testers = QLineEdit()
    self.run_testers.setPlaceholderText("Enter tester names (comma-separated)")
    self.run_testers.setToolTip("Names of the testers conducting the run, separate with commas")
    testers_layout.addWidget(self.run_testers)
    
    run_group_layout.addLayout(testers_layout)
    
    # Run description
    run_desc_layout = QVBoxLayout()
    run_desc_label = QLabel("Description:")
    run_desc_label.setFixedHeight(20) # Fixed height to prevent label stretching
    run_desc_layout.addWidget(run_desc_label)
    self.run_description = QTextEdit()
    self.run_description.setMinimumHeight(60)
    self.run_description.setPlaceholderText("Enter a description for this run")
    run_desc_layout.addWidget(self.run_description, 1) # Allow to grow
    run_group_layout.addLayout(run_desc_layout, 1) # Description takes extra space
    
    # Add run group directly to left column
    left_column_layout.addWidget(run_group)
    
    # Project actions section with modern button styles
    project_actions_group = QGroupBox("⚡ Quick Actions")
    project_actions_group.setStyleSheet("""
        QGroupBox {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2a2a50, stop:1 #1e1e40);
            border: 1px solid #4a4a7a;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 8px;
            font-size: 11px;
            font-weight: bold;
            color: #fff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 6px;
            color: #fff;
        }
    """)
    project_actions_layout = QHBoxLayout(project_actions_group)
    project_actions_layout.setSpacing(8)
    project_actions_layout.setContentsMargins(10, 10, 10, 10)
    project_actions_group.setFont(sub_font)  # Reuse the same font
    
    # Modern button style
    action_btn_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3a3a6a, stop:1 #2a2a5a);
            color: #fff;
            border: 1px solid #5a5a9a;
            border-radius: 6px;
            padding: 8px 12px;
            font-weight: bold;
            font-size: 11px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a4a7a, stop:1 #3a3a6a);
            border: 1px solid #6a6aaa;
        }
        QPushButton:pressed {
            background: #2a2a5a;
        }
    """
    
    # Import project button
    self.import_project_btn = QPushButton("📥 Import")
    self.import_project_btn.setStyleSheet(action_btn_style)
    self.import_project_btn.setMinimumWidth(90)
    self.import_project_btn.setToolTip("Import a project from a zip archive")
    project_actions_layout.addWidget(self.import_project_btn)
    
    # Export project button
    self.export_project_btn = QPushButton("📤 Export")
    self.export_project_btn.setStyleSheet(action_btn_style)
    self.export_project_btn.setMinimumWidth(90)
    self.export_project_btn.setToolTip("Export the selected project / series / run to a zip archive")
    project_actions_layout.addWidget(self.export_project_btn)
    
    # Load project button
    self.load_project_btn = QPushButton("📂 Load Run")
    self.load_project_btn.setStyleSheet(action_btn_style)
    self.load_project_btn.setMinimumWidth(100)
    self.load_project_btn.setToolTip("Load the selected run so data appears in Graphs, Dashboard, and Notes")
    project_actions_layout.addWidget(self.load_project_btn)
    
    # Delete run button
    self.delete_run_btn = QPushButton("🗑️ Delete Run")
    self.delete_run_btn.setStyleSheet(action_btn_style)
    self.delete_run_btn.setMinimumWidth(110)
    self.delete_run_btn.setToolTip("Delete the selected run folder after showing its file list for confirmation")
    project_actions_layout.addWidget(self.delete_run_btn)
    
    # Apply Settings Button for interface settings
    self.apply_settings_btn = QPushButton("⚙️ Apply Settings")
    self.apply_settings_btn.setStyleSheet(action_btn_style)
    self.apply_settings_btn.setMinimumWidth(110)
    self.apply_settings_btn.setToolTip("Apply current interface/settings changes (sampling, devices, etc.)")
    self.apply_settings_btn.clicked.connect(self.apply_settings)
    project_actions_layout.addWidget(self.apply_settings_btn)
    
    project_actions_layout.addStretch()
    
    # Right column for project browser
    right_column_widget = QWidget()
    right_column_layout = QVBoxLayout(right_column_widget)
    right_column_layout.setContentsMargins(0, 0, 0, 0)  # Remove extra margins to move left
    
    # Project browser section
    project_browser_group = QGroupBox("📂 Project Browser")
    project_browser_group.setStyleSheet(GroupBoxStyles.default())
    project_browser_group.setMinimumWidth(400) # Reduced from 750 to allow smaller window sizes
    project_browser_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    project_browser_layout = QVBoxLayout(project_browser_group)
    project_browser_layout.setContentsMargins(10, 18, 10, 10)
    
    # Set larger font for the title
    browser_font = project_browser_group.font()
    browser_font.setPointSize(12)
    browser_font.setBold(True)
    project_browser_group.setFont(browser_font)
    
    # Project tree view with improved styling
    self.project_tree = QTreeView()
    self.project_tree.setMinimumHeight(150) # Reduced from 350 to allow more height compression
    
    # Get paths for branch arrows
    arrow_right = resource_path("app/ui/arrow_right.svg").replace("\\", "/")
    arrow_down = resource_path("app/ui/arrow_down.svg").replace("\\", "/")
    
    self.project_tree.setStyleSheet(f"""
        QTreeView {{
            background-color: #1a1a35;
            border: 1px solid #3a3a6a;
            border-radius: 6px;
            padding: 5px;
            color: #ddd;
            font-size: 12px;
        }}
        QTreeView::item {{
            padding: 6px 4px;
            border-radius: 4px;
            background-color: transparent;
        }}
        QTreeView::item:hover {{
            background-color: #2a2a55;
        }}
        QTreeView::item:selected {{
            background-color: #4a4a8a;
            color: #fff;
        }}
        QTreeView::branch:has-children:closed {{
            image: url({arrow_right});
        }}
        QTreeView::branch:has-children:open {{
            image: url({arrow_down});
        }}
        QTreeView::branch:has-children:closed:hover {{
            image: url({arrow_right});
        }}
        QHeaderView::section {{
            background-color: #252550;
            color: #aaa;
            padding: 6px;
            border: none;
            border-bottom: 1px solid #3a3a6a;
            font-weight: bold;
            font-size: 11px;
        }}
    """)
    # Make the tree view read-only by disabling edit triggers
    self.project_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    # Ensure selection remains visible and active even when focus is lost
    self.project_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    self.project_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    # Set strong focus to maintain selection when focus is lost
    self.project_tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    # Keep selection highlight even when the tree loses focus
    self.project_tree.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
    self.project_tree.setAllColumnsShowFocus(True)
    self.project_model = QStandardItemModel()
    self.project_model.setHorizontalHeaderLabels(["Name", "Description", "Duration", "Sensors", "Video", "Images"])
    self.project_tree.setModel(self.project_model)
    
    # Configure header to auto-adjust columns
    project_header = self.project_tree.header()
    project_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Name: User can adjust
    project_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)      # Description: Fills space
    project_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Duration
    project_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Sensors
    project_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Video
    project_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Images
    
    # Set initial widths as fallback/minimums
    self.project_tree.setColumnWidth(0, 220)
    # Column 1 (Description) will stretch automatically
    
    project_browser_layout.addWidget(self.project_tree)
    
    # Add the Actions group at the bottom of the Project Browser
    project_browser_layout.addWidget(project_actions_group)
    
    # Add project browser group to right column
    right_column_layout.addWidget(project_browser_group)
    
    # Add right column to the splitter
    self.projects_splitter.addWidget(left_scroll_area)
    self.projects_splitter.addWidget(right_column_widget)
    
    # Set stretch factors - Project Browser (right) takes more space
    self.projects_splitter.setStretchFactor(0, 0) # Config panel takes minimum
    self.projects_splitter.setStretchFactor(1, 1) # Browser takes remainder
    
    # Set initial sizes for the horizontal splitter (increased left side width to 480px)
    self.projects_splitter.setSizes([480, 720])
    
    # Add the splitter to the container
    project_container_layout.addWidget(self.projects_splitter)
    
    # Add projects tab to stacked widget
    self.stacked_widget.addWidget(projects_tab)
    
    # Add settings tab to stacked widget
    self.stacked_widget.addWidget(settings_tab)
    
    # Add camera tab to stacked widget
    self.stacked_widget.addWidget(camera_tab)
    
    # Add sensors tab
    self.stacked_widget.addWidget(sensors_tab)
    
    # Add automation tab to stacked widget
    self.stacked_widget.addWidget(automation_tab)
    
    # Add dashboard tab in correct order with visible text
    self.stacked_widget.addWidget(dashboard_tab)
    
    # Add graphs tab to stacked widget
    self.stacked_widget.addWidget(graphs_tab)
    
    # Add stacked widget to content layout
    content_layout.addWidget(self.stacked_widget)
    
    # Add content area to main layout
    main_layout.addWidget(sidebar)
    main_layout.addWidget(content_area, 1)  # Content area takes remaining space

    # Status bar
    self.statusBar().setStyleSheet("""
        QStatusBar {
            border-top: 1px solid #ccc;
            padding: 3px;
            font-size: 12px;
        }
    """) 

    # Increase font size for all main GroupBox titles
    def set_large_font_for_groupbox(groupbox, size=11, bold=True):
        font = groupbox.font()
        font.setPointSize(size)
        font.setBold(bold)
        groupbox.setFont(font)

    # Apply larger font to main GroupBoxes
    set_large_font_for_groupbox(dashboard_graph_group)
    set_large_font_for_groupbox(camera_connection_group)
    set_large_font_for_groupbox(motion_status_group)
    set_large_font_for_groupbox(video_player_group)
    set_large_font_for_groupbox(sensor_container)
    set_large_font_for_groupbox(graph_type_group)
    set_large_font_for_groupbox(sensor_selection_group)
    set_large_font_for_groupbox(self.multi_sensor_group)
    set_large_font_for_groupbox(graph_params_group)
    set_large_font_for_groupbox(plot_format_group)
    set_large_font_for_groupbox(automation_sequences_group)
    set_large_font_for_groupbox(timelapse_group)
    
    # These already have fonts set (but we'll add them here for completeness)
    set_large_font_for_groupbox(project_browser_group, 12, True)
    set_large_font_for_groupbox(project_group, 11, True)
    set_large_font_for_groupbox(test_series_group, 11, True)
    set_large_font_for_groupbox(run_group, 11, True)
    set_large_font_for_groupbox(project_actions_group, 11, True)

    # Connect navigation buttons to switch stacked widget pages
    for i, btn in enumerate(self.nav_buttons):
        btn.clicked.connect(lambda checked, index=i: self.stacked_widget.setCurrentIndex(index)) 

    def set_timespan_to_all():
        self.graph_timespan.setCurrentText("All")

    self.graph_type_combo.currentIndexChanged.connect(set_timespan_to_all) 

    # Connect tab change signal to handle tab-specific initialization
    self.stacked_widget.currentChanged.connect(self.on_tab_changed) 

    # Connect LabJack button
    self.labjack_connect_btn.clicked.connect(self.connect_labjack)
    self.labjack_test_btn.clicked.connect(self.test_labjack)
    
    # Connect NDI checkbox
    self.enable_ndi.stateChanged.connect(self.init_ndi)

    # Connect timelapse button
    self.create_timelapse_btn.clicked.connect(lambda: show_timelapse_dialog(self))

    # --- Add Notes Tab after Graphs ---
    notes_tab = QWidget()
    self.notes_tab = notes_tab  # Store reference to avoid hardcoded indexing
    notes_tab.setStyleSheet(f"""
        QWidget {{
            background-color: {COLORS.BG_DARK};
        }}
    """)
    notes_layout = QVBoxLayout(notes_tab)
    notes_layout.setContentsMargins(10, 0, 10, 0)
    notes_layout.setSpacing(10)
    
    # HTML editor with modern theme styling
    notes_text_edit = QTextEdit()
    notes_text_edit.setAcceptRichText(True)
    notes_text_edit.setStyleSheet(f"""
        QTextEdit {{
            font-family: 'Segoe UI', sans-serif;
            font-size: 14px; 
            background: {COLORS.BG_CARD};
            color: {COLORS.TEXT_PRIMARY}; 
            border-radius: 8px; 
            padding: 12px;
            border: 1px solid {COLORS.BORDER_DEFAULT};
            selection-background-color: rgba(108, 92, 231, 0.45);
            selection-color: {COLORS.TEXT_PRIMARY};
        }}
        QTextEdit:focus {{
            border: 1px solid {COLORS.PRIMARY};
        }}
        QScrollBar:vertical {{
            background-color: {COLORS.BG_CARD};
            width: 10px;
            border-radius: 5px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background-color: {COLORS.TEXT_MUTED};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {COLORS.TEXT_SECONDARY};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
    """)
    notes_layout.addWidget(notes_text_edit, 1)
    self.notes_text_edit = notes_text_edit  # For access if needed
    self.stacked_widget.addWidget(notes_tab)

    # Add video tab to stacked widget (temporarily, will move to end)
    self.stacked_widget.addWidget(video_tab)

    # After all tabs are added, reorder the stacked_widget to match nav_buttons order
    # The order should be: Projects, Settings, Camera, Sensors, Automation, Dashboard, Graphs, Notes, Video
    # We'll remove and re-add widgets to ensure the correct order
    tab_widgets = [projects_tab, settings_tab, camera_tab, sensors_tab, automation_tab, dashboard_tab, graphs_tab, notes_tab, video_tab]
    for i, widget in enumerate(tab_widgets):
        if self.stacked_widget.indexOf(widget) != i:
            self.stacked_widget.removeWidget(widget)
            self.stacked_widget.insertWidget(i, widget)

    # Connect navigation buttons to switch stacked widget pages (fix index mapping)
    for i, btn in enumerate(self.nav_buttons):
        btn.clicked.connect(lambda checked, index=i: self.stacked_widget.setCurrentIndex(index))
    
    # Create Data Flow Monitor page (hidden from navigation, accessed via status bar or Ctrl+Shift+D)
    self.data_flow_widget = DataFlowWidget()
    self.stacked_widget.addWidget(self.data_flow_widget)
    self.data_flow_page_index = self.stacked_widget.count() - 1  # Store index for access
    
    # Apply collapsed sidebar state (since sidebar_collapsed is True by default)
    # Set to False first, then toggle to apply the collapsed state
    self.sidebar_collapsed = False
    toggle_sidebar()

def update_focus_value_label(self):
    """Update the focus value label when the slider changes"""
    if hasattr(self, 'camera_tab_focus_slider') and hasattr(self, 'camera_tab_focus_value'):
        value = self.camera_tab_focus_slider.value()
        self.camera_tab_focus_value.setText(str(value))
    
def update_exposure_value_label(self):
    """Update the exposure value label when the slider changes"""
    if hasattr(self, 'camera_tab_exposure_slider') and hasattr(self, 'camera_tab_exposure_value'):
        value = self.camera_tab_exposure_slider.value()
        self.camera_tab_exposure_value.setText(str(value))
    
def apply_camera_focus_exposure(self):
    """Apply camera focus and exposure settings"""
    if hasattr(self, 'camera_controller'):
        self.camera_controller.apply_camera_settings()

def update_device_connection_status(self, device_type, is_connected):
    """Update the connection status display for a device
    
    Args:
        device_type (str): The type of device ('arduino', 'labjack', or 'other')
        is_connected (bool): Whether the device is connected
    """
    print(f"UI update_device_connection_status called: {device_type} is_connected={is_connected}")
    
    # Define status text and colors based on connection status
    status_text = "Connected" if is_connected else "Not connected"
    status_color = "green" if is_connected else "grey"
    label_style = f"color: {status_color}; font-weight: bold; font-size: 13px; background-color: transparent; border: none; margin: 0; padding: 0;"
    
    # Define label styles
    label_style = f"color: {status_color}; font-weight: bold; font-size: 13px; background-color: transparent; border: none; margin: 0; padding: 0;"
    
    try:
        if device_type.lower() == 'arduino':
            # Update label status
            if hasattr(self, 'arduino_status'):
                print(f"Updating Arduino status label: '{status_text}' with color '{status_color}'")
                self.arduino_status.setText(status_text)
                self.arduino_status.setStyleSheet(label_style)
                
                # Update the frame style if the container exists
                arduino_container = self.arduino_status.parent()
                if arduino_container and hasattr(arduino_container, 'setStyleSheet'):
                    arduino_container.setStyleSheet(CardStyles.device_card(is_connected))
                    print(f"Updated Arduino container style for connection status: {is_connected}")
                
                # Force immediate update
                self.arduino_status.update()
                if arduino_container:
                    arduino_container.update()
                
        elif device_type.lower() == 'labjack':
            # Similar approach for labjack
            if hasattr(self, 'labjack_status'):
                print(f"Updating LabJack status label: '{status_text}' with color '{status_color}'")
                self.labjack_status.setText(status_text)
                self.labjack_status.setStyleSheet(label_style)
                
                # Update the frame style
                labjack_container = self.labjack_status.parent()
                if labjack_container and hasattr(labjack_container, 'setStyleSheet'):
                    labjack_container.setStyleSheet(CardStyles.device_card(is_connected))
                    print(f"Updated LabJack container style for connection status: {is_connected}")
                
                # Force updates
                self.labjack_status.update()
                if labjack_container:
                    labjack_container.update()
        
        elif device_type.lower() == 'other':
            # Similar approach for other
            if hasattr(self, 'other_status'):
                self.other_status.setText(status_text)
                self.other_status.setStyleSheet(label_style)
                
                # Update the frame style
                other_container = self.other_status.parent()
                if other_container and hasattr(other_container, 'setStyleSheet'):
                    other_container.setStyleSheet(CardStyles.device_card(is_connected))
                    
                # Force updates
                self.other_status.update()
                if other_container:
                    other_container.update()
    except Exception as e:
        print(f"Error updating device status: {str(e)}")
        import traceback
        traceback.print_exc()

def connect_camera(self):
    """Connect to a camera"""
    if not hasattr(self, 'camera_controller'):
        return
        
    # Forward to the controller
    if self.camera_connect_btn.text() == "Connect":
        # Check if replay is active with video - if so, stop replay video first
        if hasattr(self, 'replay_mode_enabled') and self.replay_mode_enabled:
            if hasattr(self, 'replay_active_video_path') and self.replay_active_video_path:
                # Replay video is active - clear it before connecting camera
                if hasattr(self, '_clear_replay_video'):
                    self._clear_replay_video()
        
        # Connect to the camera using the controller
        self.camera_controller.toggle_camera()
        
        # Apply focus and exposure settings after connection
        if any(self.camera_controller.is_connected):
            self.apply_camera_focus_exposure()
    else:
        # Disconnect the camera using the controller
        self.camera_controller.toggle_camera()


