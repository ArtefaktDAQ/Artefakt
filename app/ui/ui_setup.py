from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
                           QComboBox, QGroupBox, QGridLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
                           QCheckBox, QTabWidget, QTextEdit, QSizePolicy, QColorDialog, QFrame,
                           QScrollArea, QListWidget, QListWidgetItem, QSplitter, QGraphicsDropShadowEffect,
                           QHeaderView, QSlider, QTreeView, QFormLayout, QSpacerItem, QStackedWidget,
                           QToolButton, QAbstractItemView)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap, QColor, QIcon, QPainter
import pyqtgraph as pyqtgraph
from PyQt6.QtGui import QStandardItemModel
import cv2
import os
import sys

# Import the collapsible box
from app.ui.collapsible_box import CollapsibleBox
# Import timelapse utility
from app.utils.timelapse_utils import show_timelapse_dialog

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

def setup_ui(self):
    """Set up the main user interface"""
    # Create central widget
    central_widget = QWidget()
    self.setCentralWidget(central_widget)
    main_layout = QHBoxLayout(central_widget)
    main_layout.setSpacing(10)
    main_layout.setContentsMargins(10, 10, 10, 10)

    # Left sidebar
    sidebar = QWidget()
    sidebar.setFixedWidth(250)
    
    # Create shadow effect for sidebar
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(15)
    shadow.setColor(QColor(0, 0, 0, 80))
    shadow.setOffset(3, 3)
    sidebar.setGraphicsEffect(shadow)
    
    sidebar.setStyleSheet(f"""
        QWidget {{
            background: qradialgradient(cx:0.5, cy:0.3, radius:0.8, fx:0.5, fy:0.3,
                                      stop:0 #3A0663, stop:0.6 #28043D, stop:1 #1A022A);
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        QLabel {{
            border: none;
            background: transparent;
        }}
    """)
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setSpacing(1)
    sidebar_layout.setContentsMargins(0, 20, 0, 20)

    # Program name (Artefakt)
    program_name_text = QLabel("Artefakt")
    program_name_text.setStyleSheet("""
        font-size: 24px;
        font-weight: bold;
        color: rgba(255, 255, 255, 0.9);
        background: transparent;
    """)
    program_name_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sidebar_layout.addWidget(program_name_text)
    
    # Version text without logo
    version_text = QLabel(f"DAQ <span style='font-size: 14px;'>v{__version__}</span>")
    version_text.setStyleSheet("""
        font-size: 18px;
        font-weight: bold;
        color: rgba(255, 255, 255, 0.7);
        background: transparent;
    """)
    version_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sidebar_layout.addWidget(version_text)
    
    # Add vertical spacing after the version text
    vertical_spacer = QSpacerItem(20, 15, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    sidebar_layout.addItem(vertical_spacer)
    
    # Add separator
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); margin: 10px 30px;")
    sidebar_layout.addWidget(separator)
    
    # Project status section
    project_status_container = QWidget()
    project_status_container.setStyleSheet("background: transparent; border: none;")
    project_status_layout = QVBoxLayout(project_status_container)
    project_status_layout.setContentsMargins(20, 5, 20, 5)
    
    # Project status label
    project_status_label = QLabel("Project Status")
    project_status_label.setStyleSheet("""
        font-size: 14px;
        font-weight: bold;
        color: white;
        background: transparent;
    """)
    project_status_layout.addWidget(project_status_label)
    
    # Project name
    project_name_layout = QHBoxLayout()
    project_name_layout.addWidget(QLabel("Project:      "))
    self.sidebar_project_name = QLabel("None")
    self.sidebar_project_name.setStyleSheet("color: #4CAF50;")  # Green color
    project_name_layout.addWidget(self.sidebar_project_name, 1)
    project_status_layout.addLayout(project_name_layout)
    
    # Test series name
    test_series_layout = QHBoxLayout()
    test_series_layout.addWidget(QLabel("Test Series:"))
    self.sidebar_test_series = QLabel("None")
    self.sidebar_test_series.setStyleSheet("color: #4CAF50;")  # Green color
    test_series_layout.addWidget(self.sidebar_test_series, 1)
    project_status_layout.addLayout(test_series_layout)
    
    # Ready status
    ready_layout = QHBoxLayout()
    ready_layout.addWidget(QLabel("Run Status:"))
    self.sidebar_ready_status = QLabel("Not Ready")
    self.sidebar_ready_status.setStyleSheet("color: orange;")
    ready_layout.addWidget(self.sidebar_ready_status, 1)
    project_status_layout.addLayout(ready_layout)
    
    sidebar_layout.addWidget(project_status_container)
    
    # Add separator
    separator2 = QFrame()
    separator2.setFrameShape(QFrame.Shape.HLine)
    separator2.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); margin: 10px 20px;")
    sidebar_layout.addWidget(separator2)
    
    # Add spacer to push controls to bottom
    sidebar_layout.addStretch()

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

    # Create a button style specifically for tool buttons with text under icon
    tool_button_style = """
        QToolButton {
            text-align: center;
            padding: 6px 6px;
            font-size: 13px;
            color: white;
            border: none;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            border-bottom: 1px solid rgba(0, 0, 0, 0.2);
            background: transparent;
            qproperty-toolButtonStyle: ToolButtonTextUnderIcon;
        }
        QToolButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 rgba(255, 255, 255, 0.1), stop:1 rgba(255, 255, 255, 0.05));
        }
        QToolButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 rgba(255, 255, 255, 0.2), stop:1 rgba(255, 255, 255, 0.1));
            border-bottom: 1px solid #60BD60;
        }
        QToolButton:checked {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 rgba(255, 255, 255, 0.15), stop:1 rgba(255, 255, 255, 0.05));
            border-left: 3px solid #9370DB;
            border-right: 3px solid transparent;
        }
    """

    self.nav_buttons = []
    for button_name in nav_buttons:
        # Create a tool button with icon on top and text below
        btn = QToolButton()
        btn.setStyleSheet(tool_button_style)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setText(button_name)
        
        # Load SVG icon and set it
        svg_path = resource_path(f"app/ui/{button_name}.svg")
        btn.setIcon(QIcon(svg_path))
        btn.setIconSize(QSize(36, 36))
        
        # Set the tool button style to text under icon
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        
        # Ensure the button takes full width
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Add spacing between specific buttons
        if button_name == "Projects" or button_name == "Settings":
            sidebar_layout.addWidget(btn)
            # Add spacer after Projects (and before Camera)
            if button_name == "Projects":
                spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                sidebar_layout.addItem(spacer)
        elif button_name == "Automation":
            sidebar_layout.addWidget(btn)
            # Add spacer after Automation (and before Dashboard)
            spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
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
    
    # Style for toggle button - start state
    self.start_btn_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #A0EEA0, stop:1 #70CD70);
            color: #003300;
            border: none;
            padding: 8px 15px;
            border-radius: 5px;
            font-weight: bold;
            font-size: 16px;
            border-bottom: 2px solid #60BD60;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #B0FFB0, stop:1 #80DD80);
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #80DD80, stop:1 #60BD60);
            border-bottom: 1px solid #60BD60;
            padding-top: 9px;
        }
    """
    
    # Style for toggle button - stop state
    self.stop_btn_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #FFB6C1, stop:1 #FF8A9A);
            color: #330000;
            border: none;
            padding: 8px 15px;
            border-radius: 5px;
            font-weight: bold;
            font-size: 16px;
            border-bottom: 2px solid #FF7A8A;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #FFC6D1, stop:1 #FF9AAA);
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #FF9AAA, stop:1 #FF7A8A);
            border-bottom: 1px solid #FF7A8A;
            padding-top: 9px;
        }
    """
    
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
    logo_label = QLabel()
    try:
        logo_pixmap = QPixmap(resource_path("assets/Evo-Labs_logo.png"))
        if not logo_pixmap.isNull():
            scaled_pixmap = logo_pixmap.scaled(140, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setStyleSheet("background: transparent;")
            sidebar_layout.addWidget(logo_label)
    except Exception as e:
        pass  # No fallback text - just skip the logo if it can't be loaded

    # Main content area
    content_area = QWidget()
    content_layout = QHBoxLayout(content_area)
    content_layout.setSpacing(10)
    content_layout.setContentsMargins(10, 10, 10, 10)

    # Create stacked widget with visible tab bar
    self.stacked_widget = QStackedWidget()

    # Dashboard tab
    dashboard_tab = QWidget()
    dashboard_layout = QVBoxLayout(dashboard_tab)
    
    # Create a splitter to allow dragging between upper and lower parts
    dashboard_splitter = QSplitter(Qt.Orientation.Vertical)
    dashboard_splitter.setChildrenCollapsible(False)  # Prevent sections from being collapsed completely
    
    # Upper part - Dashboard graph widget
    upper_widget = QWidget()
    upper_layout = QVBoxLayout(upper_widget)
    upper_layout.setContentsMargins(0, 0, 0, 0)
    
    # Dashboard graph widget
    dashboard_graph_group = QGroupBox("Sensor Overview")
    dashboard_graph_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    
    # Create a horizontal layout for the graph and controls
    dashboard_graph_container = QHBoxLayout(dashboard_graph_group)
    
    # Left side controls panel
    dashboard_controls_panel = QVBoxLayout()
    dashboard_controls_panel.setAlignment(Qt.AlignmentFlag.AlignTop)
    dashboard_controls_panel.setContentsMargins(0, 10, 10, 0)
    
    # Timespan label and dropdown in vertical layout
    dashboard_controls_panel.addWidget(QLabel("Timespan:"))
    self.dashboard_timespan = QComboBox()
    self.dashboard_timespan.addItems(["10s", "30s", "1min", "5min", "15min", "30min", "1h", "3h", "6h", "12h", "24h", "All"])
    self.dashboard_timespan.setCurrentText("All")  # Default to All
    dashboard_controls_panel.addWidget(self.dashboard_timespan)
    
    # Add stretch to push controls to the top
    dashboard_controls_panel.addStretch(1)
    
    # Add controls panel to the left side of the container
    dashboard_graph_container.addLayout(dashboard_controls_panel)
    
    # Dashboard graph widget in a vertical layout
    dashboard_graph_layout = QVBoxLayout()
    self.dashboard_graph_widget = pyqtgraph.PlotWidget()
    # Apply dark theme settings
    self.dashboard_graph_widget.setBackground('#2D2D2D')
    self.dashboard_graph_widget.getAxis('bottom').setPen('#BBBBBB')
    self.dashboard_graph_widget.getAxis('left').setPen('#BBBBBB')
    self.dashboard_graph_widget.getAxis('bottom').setTextPen('#EEEEEE')
    self.dashboard_graph_widget.getAxis('left').setTextPen('#EEEEEE')
    self.dashboard_graph_widget.showGrid(x=True, y=True, alpha=0.2)
    self.dashboard_graph_widget.setLabel('left', 'Value')
    self.dashboard_graph_widget.setLabel('bottom', 'Sample Count')
    self.dashboard_graph_widget.addLegend()
    dashboard_graph_layout.addWidget(self.dashboard_graph_widget)
    
    # Add graph layout to the container (takes most of the space)
    dashboard_graph_container.addLayout(dashboard_graph_layout, 1)
    
    # Add dashboard graph to upper layout
    upper_layout.addWidget(dashboard_graph_group, 1)
    
    # Connect dashboard graph controls to update function
    self.dashboard_timespan.currentIndexChanged.connect(lambda: self.on_timespan_changed(self.dashboard_graph_widget, False) if hasattr(self, 'on_timespan_changed') else self.update_dashboard_graph())
    
    # Add upper widget to splitter
    dashboard_splitter.addWidget(upper_widget)
    
    # Lower part - Automation Status and Camera Preview with Splitter
    lower_widget = QWidget()
    # Use QVBoxLayout for the main lower widget container
    lower_layout = QVBoxLayout(lower_widget) 
    lower_layout.setContentsMargins(0, 0, 0, 0)
    
    # Create a horizontal splitter for the two panels
    lower_splitter = QSplitter(Qt.Orientation.Horizontal)
    lower_splitter.setChildrenCollapsible(False)

    # Automation Status panel (Left side)
    dashboard_automation_group = QGroupBox("Automation Status")
    dashboard_automation_layout = QVBoxLayout(dashboard_automation_group)

    # --- ADDED --- New table for detailed status
    self.dashboard_automation_table = QTableWidget()
    self.dashboard_automation_table.setColumnCount(5)
    self.dashboard_automation_table.setHorizontalHeaderLabels(["Sequence", "Status", "Current Step", "Next Step", "Time/Trigger"])
    # Allow columns to resize, make Sequence name stretch
    header = self.dashboard_automation_table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Sequence
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Status
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch) # Current Step
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch) # Next Step
    header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Time/Trigger
    self.dashboard_automation_table.verticalHeader().setVisible(False) # Hide row numbers
    # --- CORRECTED --- Use SelectionMode to disable selection
    self.dashboard_automation_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    self.dashboard_automation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # Make read-only
    self.dashboard_automation_table.setAlternatingRowColors(True)
    dashboard_automation_layout.addWidget(self.dashboard_automation_table)

    dashboard_automation_group.setMinimumWidth(350) # Give it a slightly wider minimum width for the table

    # Add automation group to the splitter
    lower_splitter.addWidget(dashboard_automation_group)

    # Camera preview group box (Right side)
    dashboard_camera_group = QGroupBox("Camera Preview")
    dashboard_camera_layout = QVBoxLayout(dashboard_camera_group)
    
    # Camera preview label
    self.dashboard_camera_label = QLabel("No camera connected")
    self.dashboard_camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.dashboard_camera_label.setStyleSheet("background-color: #222; color: white;")
    self.dashboard_camera_label.setMinimumHeight(150)
    dashboard_camera_layout.addWidget(self.dashboard_camera_label)
    
    # Add camera group to the splitter
    lower_splitter.addWidget(dashboard_camera_group)

    # Set initial sizes for the horizontal splitter (e.g., 30% automation, 70% camera)
    lower_splitter.setSizes([30, 70])

    # Add the splitter to the lower layout
    lower_layout.addWidget(lower_splitter)
    
    # Add lower widget to the main vertical splitter
    dashboard_splitter.addWidget(lower_widget)
    
    # Set initial sizes for the splitter (60% for graph, 40% for camera)
    dashboard_splitter.setSizes([60, 40])
    
    # Add splitter to dashboard layout
    dashboard_layout.addWidget(dashboard_splitter, 1)
    
    # Add a description label
    dashboard_description = QLabel("This graph shows all active sensors that are enabled in the Sensors tab with 'Show in Graph' checked.")
    dashboard_description.setStyleSheet("color: #666; font-style: italic;")
    dashboard_layout.addWidget(dashboard_description)
    
    # Add tabs in correct order with visible text
    self.stacked_widget.addWidget(dashboard_tab)
    
    # Create Camera Tab
    camera_tab = QWidget()
    camera_layout = QHBoxLayout(camera_tab)
    
    # Define common button style for camera tab buttons
    camera_button_style = """
        QPushButton {
            background-color: transparent;  /* Transparent background */
            border: 2px solid #b3d9ff;  /* Blue border */
            border-radius: 3px;
            padding: 3px 6px;
            font-size: 12px;
            min-height: 22px;
            max-height: 22px;
        }
        QPushButton:hover {
            background-color: rgba(179, 217, 255, 0.15);  /* Semi-transparent blue on hover */
            border-color: #80b3ff;  /* Darker blue border on hover */
        }
        QPushButton:pressed {
            background-color: rgba(179, 217, 255, 0.3);  /* More opaque blue when pressed */
            border-color: #6699ff;  /* Even darker blue border when pressed */
        }
    """
    
    # Define green button style for connect and apply buttons
    green_button_style = """
        QPushButton {
            background-color: transparent;  /* Transparent background */
            border: 2px solid #4CAF50;  /* Intense green border */
            border-radius: 3px;
            padding: 3px 6px;
            font-size: 12px;
            min-height: 22px;
            max-height: 22px;
        }
        QPushButton:hover {
            background-color: rgba(76, 175, 80, 0.15);  /* Semi-transparent green on hover */
            border-color: #3d8b40;  /* Darker green border on hover */
        }
        QPushButton:pressed {
            background-color: rgba(76, 175, 80, 0.3);  /* More opaque green when pressed */
            border-color: #2e6830;  /* Even darker green border when pressed */
        }
    """
    
    # Define red button style for remove overlay button
    red_button_style = """
        QPushButton {
            background-color: transparent;  /* Transparent background */
            border: 2px solid #F44336;  /* Intense red border */
            border-radius: 3px;
            padding: 3px 6px;
            font-size: 12px;
            min-height: 22px;
            max-height: 22px;
        }
        QPushButton:hover {
            background-color: rgba(244, 67, 54, 0.15);  /* Semi-transparent red on hover */
            border-color: #d32f2f;  /* Darker red border on hover */
        }
        QPushButton:pressed {
            background-color: rgba(244, 67, 54, 0.3);  /* More opaque red when pressed */
            border-color: #b71c1c;  /* Even darker red border when pressed */
        }
    """
    
    # Create a splitter for the camera tab
    camera_splitter = QSplitter(Qt.Orientation.Horizontal)
    camera_layout.addWidget(camera_splitter)
    
    # Left side - Camera settings
    camera_settings_container = QWidget()
    camera_settings_container.setMinimumWidth(300)
    camera_settings_container.setMaximumWidth(380)
    camera_settings_layout = QVBoxLayout(camera_settings_container)
    
    # Camera settings button
    self.camera_settings_btn = QPushButton("Camera Settings")
    self.camera_settings_btn.setFixedHeight(30)
    self.camera_settings_btn.setStyleSheet(green_button_style)
    self.camera_settings_btn.clicked.connect(self.show_camera_settings_popup)
    camera_settings_layout.addWidget(self.camera_settings_btn)
    
    # Camera connection settings
    camera_connection_group = QGroupBox("Camera Connection")
    camera_connection_layout = QGridLayout(camera_connection_group)
    
    # Store the reference to the group box in the main window
    self.camera_connection_group = camera_connection_group
    
    # Camera selection
    camera_connection_layout.addWidget(QLabel("Camera:"), 0, 0)
    self.camera_id = QComboBox()
    self.camera_id.addItems(["0", "1", "2", "3"])
    camera_connection_layout.addWidget(self.camera_id, 0, 1)
    
    # Connect button
    self.camera_connect_btn = QPushButton("Connect")
    self.camera_connect_btn.setFixedSize(80, 22)
    self.camera_connect_btn.setStyleSheet(green_button_style)  # Green connect button
    # Don't connect signal here - will be connected in setup.py
    # self.camera_connect_btn.clicked.connect(self.connect_camera)
    camera_connection_layout.addWidget(self.camera_connect_btn, 0, 2)
    
    # Add camera connection group to settings layout
    camera_settings_layout.addWidget(camera_connection_group)
    
    # Camera focus and exposure controls
    camera_controls_group = QGroupBox("Camera Controls")
    camera_controls_layout = QGridLayout(camera_controls_group)
    
    # Manual focus controls
    self.camera_tab_manual_focus = QCheckBox("Manual Focus")
    self.camera_tab_manual_focus.setToolTip("Enable to manually control camera focus")
    initial_manual_focus = self.settings.value("camera/manual_focus", "true").lower() == "true"
    self.camera_tab_manual_focus.setChecked(initial_manual_focus)
    camera_controls_layout.addWidget(self.camera_tab_manual_focus, 0, 0, 1, 3)
    
    # Focus slider with value label
    focus_slider_layout = QHBoxLayout()
    self.camera_tab_focus_slider = QSlider(Qt.Orientation.Horizontal)
    self.camera_tab_focus_slider.setMinimum(0)
    self.camera_tab_focus_slider.setMaximum(255)
    self.camera_tab_focus_slider.setValue(int(self.settings.value("camera/focus_value", "0")))
    self.camera_tab_focus_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    self.camera_tab_focus_slider.setTickInterval(50)
    self.camera_tab_focus_slider.setEnabled(initial_manual_focus)
    focus_slider_layout.addWidget(self.camera_tab_focus_slider, 1)
    
    # Value display for focus
    self.camera_tab_focus_value = QLabel(str(self.camera_tab_focus_slider.value()))
    self.camera_tab_focus_value.setMinimumWidth(30)
    self.camera_tab_focus_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    focus_slider_layout.addWidget(self.camera_tab_focus_value)
    camera_controls_layout.addLayout(focus_slider_layout, 1, 0, 1, 3)
    
    # Manual exposure controls
    self.camera_tab_manual_exposure = QCheckBox("Manual Exposure")
    self.camera_tab_manual_exposure.setToolTip("Enable to manually control camera exposure")
    initial_manual_exposure = self.settings.value("camera/manual_exposure", "true").lower() == "true"
    self.camera_tab_manual_exposure.setChecked(initial_manual_exposure)
    camera_controls_layout.addWidget(self.camera_tab_manual_exposure, 2, 0, 1, 3)
    
    # Exposure slider with value label
    exposure_slider_layout = QHBoxLayout()
    self.camera_tab_exposure_slider = QSlider(Qt.Orientation.Horizontal)
    self.camera_tab_exposure_slider.setMinimum(-13)  # Exposure values can be negative
    self.camera_tab_exposure_slider.setMaximum(13)
    self.camera_tab_exposure_slider.setValue(int(self.settings.value("camera/exposure_value", "0")))
    self.camera_tab_exposure_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    self.camera_tab_exposure_slider.setTickInterval(5)
    self.camera_tab_exposure_slider.setEnabled(initial_manual_exposure)
    exposure_slider_layout.addWidget(self.camera_tab_exposure_slider, 1)
    
    # Value display for exposure
    self.camera_tab_exposure_value = QLabel(str(self.camera_tab_exposure_slider.value()))
    self.camera_tab_exposure_value.setMinimumWidth(30)
    self.camera_tab_exposure_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    exposure_slider_layout.addWidget(self.camera_tab_exposure_value)
    camera_controls_layout.addLayout(exposure_slider_layout, 3, 0, 1, 3)
    
    # Add camera controls group to settings layout
    camera_settings_layout.addWidget(camera_controls_group)
    
    # Motion indicator in camera tab
    motion_status_group = QGroupBox("Motion Status")
    motion_status_layout = QHBoxLayout(motion_status_group)
    
    motion_status_layout.addWidget(QLabel("Motion Detection:"))
    self.motion_detection_indicator = QLabel()
    self.motion_detection_indicator.setFixedSize(20, 20)
    self.motion_detection_indicator.setStyleSheet("background-color: green; border-radius: 5px;")
    self.motion_detection_indicator.setToolTip("Green: No motion detected | Red: Motion detected")
    motion_status_layout.addWidget(self.motion_detection_indicator)
    motion_status_layout.addStretch()
    
    # Add motion status group to settings layout
    camera_settings_layout.addWidget(motion_status_group)
    
    # Overlay settings - Make it collapsible
    overlay_collapsible = CollapsibleBox("Overlay Settings")
    
    # Create widget with fixed size policy to avoid stretching
    overlay_widget = QWidget()
    overlay_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    # Create layout with compact spacing
    overlay_settings_layout = QGridLayout(overlay_widget)
    overlay_settings_layout.setContentsMargins(5, 5, 5, 5)
    overlay_settings_layout.setVerticalSpacing(5)
    overlay_settings_layout.setHorizontalSpacing(10)

    # Overlay selection
    overlay_settings_layout.addWidget(QLabel("Overlay:"), 0, 0)
    self.overlay_selector = QComboBox()
    overlay_settings_layout.addWidget(self.overlay_selector, 0, 1)

    # Text size (font scale)
    overlay_settings_layout.addWidget(QLabel("Font Scale:"), 1, 0)
    self.overlay_font_scale = QDoubleSpinBox()
    self.overlay_font_scale.setRange(0.1, 3.0)
    self.overlay_font_scale.setSingleStep(0.1)
    self.overlay_font_scale.setValue(0.7)
    overlay_settings_layout.addWidget(self.overlay_font_scale, 1, 1)

    # Line thickness
    overlay_settings_layout.addWidget(QLabel("Thickness:"), 2, 0)
    self.overlay_thickness = QSpinBox()
    self.overlay_thickness.setRange(1, 5)
    self.overlay_thickness.setValue(2)
    overlay_settings_layout.addWidget(self.overlay_thickness, 2, 1)
    
    # Text color (RGB components) - Make it less tall
    text_color_group = QGroupBox("Text Color")
    text_color_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    text_color_layout = QHBoxLayout(text_color_group)
    text_color_layout.setContentsMargins(5, 5, 5, 5)

    # Color preview box - Shorter height
    self.text_color_preview = QFrame()
    self.text_color_preview.setFixedSize(50, 18)  # Further reduced size
    self.text_color_preview.setStyleSheet("background-color: rgb(0, 255, 0); border: 1px solid #888;")
    text_color_layout.addWidget(self.text_color_preview)

    # Color picker button
    self.text_color_picker_btn = QPushButton("Color")
    self.text_color_picker_btn.setFixedSize(60, 20)
    self.text_color_picker_btn.setStyleSheet(camera_button_style)
    self.text_color_picker_btn.clicked.connect(self.choose_text_color)
    text_color_layout.addWidget(self.text_color_picker_btn)
    text_color_layout.addStretch()  # Add stretch to prevent expanding

    # Store RGB values in hidden variables
    self.overlay_text_color_r = QSpinBox()
    self.overlay_text_color_r.setVisible(False)
    self.overlay_text_color_r.setRange(0, 255)
    self.overlay_text_color_r.setValue(0)

    self.overlay_text_color_g = QSpinBox()
    self.overlay_text_color_g.setVisible(False)
    self.overlay_text_color_g.setRange(0, 255)
    self.overlay_text_color_g.setValue(255)

    self.overlay_text_color_b = QSpinBox()
    self.overlay_text_color_b.setVisible(False)
    self.overlay_text_color_b.setRange(0, 255)
    self.overlay_text_color_b.setValue(0)

    overlay_settings_layout.addWidget(text_color_group, 3, 0, 1, 2)

    # Background color (RGB components) - Make it less tall and include opacity
    bg_color_group = QGroupBox("Background Color")
    bg_color_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    bg_color_layout = QHBoxLayout(bg_color_group)
    bg_color_layout.setContentsMargins(5, 5, 5, 5)

    # Color preview box - Shorter height
    self.bg_color_preview = QFrame()
    self.bg_color_preview.setFixedSize(50, 18)  # Further reduced size
    self.bg_color_preview.setStyleSheet("background-color: rgba(0, 0, 0, 0.7); border: 1px solid #888;")
    bg_color_layout.addWidget(self.bg_color_preview)

    # Color picker button
    self.bg_color_picker_btn = QPushButton("Color")
    self.bg_color_picker_btn.setFixedSize(60, 20)
    self.bg_color_picker_btn.setStyleSheet(camera_button_style)
    self.bg_color_picker_btn.clicked.connect(self.choose_bg_color)
    bg_color_layout.addWidget(self.bg_color_picker_btn)
    bg_color_layout.addStretch()  # Add stretch to prevent expanding

    # Store RGB values in hidden variables
    self.overlay_bg_color_r = QSpinBox()
    self.overlay_bg_color_r.setVisible(False)
    self.overlay_bg_color_r.setRange(0, 255)
    self.overlay_bg_color_r.setValue(0)

    self.overlay_bg_color_g = QSpinBox()
    self.overlay_bg_color_g.setVisible(False)
    self.overlay_bg_color_g.setRange(0, 255)
    self.overlay_bg_color_g.setValue(0)

    self.overlay_bg_color_b = QSpinBox()
    self.overlay_bg_color_b.setVisible(False)
    self.overlay_bg_color_b.setRange(0, 255)
    self.overlay_bg_color_b.setValue(0)

    # Add opacity control
    bg_opacity_layout = QHBoxLayout()
    bg_opacity_layout.addWidget(QLabel("Opacity:"))
    self.overlay_bg_alpha = QSpinBox()
    self.overlay_bg_alpha.setRange(0, 100)
    self.overlay_bg_alpha.setSingleStep(5)
    self.overlay_bg_alpha.setValue(70)
    self.overlay_bg_alpha.setMinimumWidth(60)  # Set minimum width to ensure numbers are fully visible
    self.overlay_bg_alpha.valueChanged.connect(self.apply_overlay_settings)  # Apply settings immediately when opacity changes
    bg_opacity_layout.addWidget(self.overlay_bg_alpha)
    bg_opacity_layout.addStretch()  # Add stretch to prevent expanding
    bg_color_layout.addLayout(bg_opacity_layout)
    
    # For backward compatibility (same as overlay_bg_alpha)
    self.overlay_bg_opacity = self.overlay_bg_alpha

    overlay_settings_layout.addWidget(bg_color_group, 4, 0, 1, 2)

    # Add collapsible sections for advanced settings
    # Text content (placeholder, source, prefix, suffix)
    text_content_collapsible = CollapsibleBox("Text Content")
    text_content_layout = QGridLayout()
    text_content_layout.setVerticalSpacing(5)

    text_content_layout.addWidget(QLabel("Placeholder:"), 0, 0)
    self.overlay_placeholder = QLineEdit("Sample text")
    text_content_layout.addWidget(self.overlay_placeholder, 0, 1)

    text_content_layout.addWidget(QLabel("Data Source:"), 1, 0)
    self.overlay_data_source = QComboBox()
    self.overlay_data_source.addItems(["Static Text", "Date/Time", "Timestamp", "Sensor Data", "Counter", "Calculated"])
    text_content_layout.addWidget(self.overlay_data_source, 1, 1)

    text_content_layout.addWidget(QLabel("Prefix:"), 2, 0)
    self.overlay_prefix = QLineEdit()
    text_content_layout.addWidget(self.overlay_prefix, 2, 1)

    text_content_layout.addWidget(QLabel("Suffix:"), 3, 0)
    self.overlay_suffix = QLineEdit()
    text_content_layout.addWidget(self.overlay_suffix, 3, 1)

    text_content_collapsible.setContentLayout(text_content_layout)
    overlay_settings_layout.addWidget(text_content_collapsible, 5, 0, 1, 2)

    # Format settings (format string, precision, etc)
    format_collapsible = CollapsibleBox("Format Settings")
    format_layout = QGridLayout()
    format_layout.setVerticalSpacing(5)

    format_layout.addWidget(QLabel("Format:"), 0, 0)
    self.overlay_format = QLineEdit()
    self.overlay_format.setPlaceholderText("e.g., %.2f")
    format_layout.addWidget(self.overlay_format, 0, 1)

    format_layout.addWidget(QLabel("Precision:"), 1, 0)
    self.overlay_precision = QSpinBox()
    self.overlay_precision.setRange(0, 10)
    self.overlay_precision.setValue(2)
    format_layout.addWidget(self.overlay_precision, 1, 1)

    format_collapsible.setContentLayout(format_layout)
    overlay_settings_layout.addWidget(format_collapsible, 6, 0, 1, 2)

    # Dimensions settings (width, height)
    dimensions_collapsible = CollapsibleBox("Dimensions")
    dimensions_layout = QGridLayout()
    dimensions_layout.setVerticalSpacing(5)

    dimensions_layout.addWidget(QLabel("Width:"), 0, 0)
    self.overlay_width = QSpinBox()
    self.overlay_width.setRange(10, 800)
    self.overlay_width.setValue(150)
    dimensions_layout.addWidget(self.overlay_width, 0, 1)

    dimensions_layout.addWidget(QLabel("Height:"), 1, 0)
    self.overlay_height = QSpinBox()
    self.overlay_height.setRange(10, 600)
    self.overlay_height.setValue(80)
    dimensions_layout.addWidget(self.overlay_height, 1, 1)

    dimensions_collapsible.setContentLayout(dimensions_layout)
    overlay_settings_layout.addWidget(dimensions_collapsible, 7, 0, 1, 2)

    # Add action buttons in a more compact layout
    buttons_layout = QHBoxLayout()
    buttons_layout.setSpacing(5)

    # Apply overlay settings button
    self.apply_overlay_settings_btn = QPushButton("Apply Settings")
    self.apply_overlay_settings_btn.setFixedSize(100, 22)
    self.apply_overlay_settings_btn.setStyleSheet(green_button_style)
    self.apply_overlay_settings_btn.clicked.connect(self.apply_overlay_settings)
    buttons_layout.addWidget(self.apply_overlay_settings_btn)

    # Remove overlay button
    self.remove_overlay_btn = QPushButton("Remove Overlay")
    self.remove_overlay_btn.setFixedSize(100, 22)
    self.remove_overlay_btn.setStyleSheet(red_button_style)
    self.remove_overlay_btn.clicked.connect(self.remove_overlay)
    buttons_layout.addWidget(self.remove_overlay_btn)

    overlay_settings_layout.addLayout(buttons_layout, 8, 0, 1, 2)

    # Set the content layout for the overlay collapsible box
    overlay_widget.setMinimumWidth(250)  # Set minimum width to ensure buttons are fully visible
    overlay_collapsible.setContentLayout(overlay_settings_layout)

    # Store references to the collapsible groups and content groups for controller access
    self.overlay_text_content_group = text_content_collapsible
    self.overlay_format_group = format_collapsible
    self.overlay_dimensions_group = dimensions_collapsible

    # Add overlay collapsible box to settings layout
    camera_settings_layout.addWidget(overlay_collapsible)
    
    # Add stretch to push everything to the top
    camera_settings_layout.addStretch()
    
    # Right side - Camera view and controls
    camera_view_container = QWidget()
    camera_view_layout = QVBoxLayout(camera_view_container)
    
    # Camera view
    self.camera_label = QLabel("No camera connected")
    self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.camera_label.setStyleSheet("background-color: #222; color: white;")
    self.camera_label.setMinimumSize(640, 480)
    
    # Enable mouse tracking for overlay dragging
    self.camera_label.setMouseTracking(True)
    self.camera_label.mousePressEvent = self.camera_mouse_press
    self.camera_label.mouseReleaseEvent = self.camera_mouse_release
    self.camera_label.mouseMoveEvent = self.camera_mouse_move
    
    camera_view_layout.addWidget(self.camera_label)
    
    # Camera controls
    camera_controls = QHBoxLayout()
    
    # Snapshot button
    self.snapshot_btn = QPushButton("Take Snapshot")
    self.snapshot_btn.setFixedSize(120, 22)  # Wider button
    self.snapshot_btn.setStyleSheet(camera_button_style)
    self.snapshot_btn.clicked.connect(self.take_snapshot)
    self.snapshot_btn.setEnabled(False)  # Disabled at startup
    
    # Record button
    self.record_btn = QPushButton("Start Recording")
    self.record_btn.setFixedSize(120, 22)  # Wider button
    self.record_btn.setStyleSheet(camera_button_style)
    self.record_btn.clicked.connect(self.toggle_recording)
    self.record_btn.setEnabled(False)  # Disabled at startup
    
    # Add overlay button
    self.add_overlay_btn = QPushButton("Add Overlay")
    self.add_overlay_btn.setFixedSize(120, 22)  # Wider button
    self.add_overlay_btn.setStyleSheet(camera_button_style)
    self.add_overlay_btn.clicked.connect(self.add_overlay)
    self.add_overlay_btn.setEnabled(False)  # Disabled at startup
    
    # Add buttons to layout with less spacing
    camera_controls.addWidget(self.snapshot_btn)
    camera_controls.addWidget(self.record_btn)
    camera_controls.addWidget(self.add_overlay_btn)
    camera_controls.addStretch()  # Push buttons to the left
    camera_controls.setSpacing(5)  # Reduce spacing between buttons
    
    camera_view_layout.addLayout(camera_controls)
    
    # Add camera settings container to the splitter
    camera_splitter.addWidget(camera_settings_container)
    
    # Add camera view container to the splitter
    camera_splitter.addWidget(camera_view_container)
    
    # Set initial sizes for the splitter (30% for settings, 70% for camera view)
    camera_splitter.setSizes([300, 700])
    
    # Add camera tab to stacked widget
    self.stacked_widget.addWidget(camera_tab)
    
    # Video tab
    video_tab = QWidget()
    video_layout = QVBoxLayout(video_tab)
    
    # Video player section
    video_player_group = QGroupBox("Video Player")
    video_player_layout = QVBoxLayout(video_player_group)
    
    # Video display area
    self.video_display = QLabel("No video loaded")
    self.video_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.video_display.setMinimumHeight(400)
    self.video_display.setStyleSheet("background-color: #222; color: #888; border: 1px solid #444;")
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
    
    # Add the video tab to the stacked widget
    self.stacked_widget.addWidget(video_tab)
    
    # Create Sensors Tab
    sensors_tab = QWidget()
    sensors_layout = QVBoxLayout(sensors_tab)
    
    # Create a fixed-width container for sensors content
    sensors_container = QWidget()
    sensors_container.setFixedWidth(800)  # Set a reasonable fixed width
    sensors_container_layout = QVBoxLayout(sensors_container)
    sensors_container_layout.setContentsMargins(0, 0, 0, 0)
    
    # Center the container in the tab
    sensors_layout.addWidget(sensors_container, 0, Qt.AlignmentFlag.AlignCenter)
    
    # Add device status section with images
    devices_status_container = QWidget()
    devices_status_layout = QGridLayout(devices_status_container)
    devices_status_layout.setContentsMargins(0, 0, 0, 0)
    devices_status_layout.setHorizontalSpacing(30)  # Reduced space between columns
    devices_status_layout.setVerticalSpacing(5)     # Space between rows
    
    # Create framed containers for each device with hover and click functionality
    # Arduino container
    arduino_container = QFrame()
    arduino_container.setFrameShape(QFrame.Shape.Box)
    arduino_container.setFrameShadow(QFrame.Shadow.Raised)
    arduino_container.setLineWidth(2)
    arduino_container.setStyleSheet("""
        QFrame { 
            border: 2px solid #999; 
            border-radius: 8px; 
            background-color: transparent; 
        }
        QFrame:hover { 
            background-color: rgba(200, 200, 200, 0.3); 
            border: 2px solid #777; 
        }
    """)
    arduino_container.setCursor(Qt.CursorShape.PointingHandCursor)  # Change cursor to hand pointer
    arduino_layout = QVBoxLayout(arduino_container)
    arduino_layout.setContentsMargins(5, 5, 5, 5)  # Reduce padding
    arduino_layout.setSpacing(2)  # Reduce spacing between elements

    # Labjack container
    labjack_container = QFrame()
    labjack_container.setFrameShape(QFrame.Shape.Box)
    labjack_container.setFrameShadow(QFrame.Shadow.Raised)
    labjack_container.setLineWidth(2)
    labjack_container.setStyleSheet("""
        QFrame { 
            border: 2px solid #999; 
            border-radius: 8px; 
            background-color: transparent; 
        }
        QFrame:hover { 
            background-color: rgba(200, 200, 200, 0.3); 
            border: 2px solid #777; 
        }
    """)
    labjack_container.setCursor(Qt.CursorShape.PointingHandCursor)  # Change cursor to hand pointer
    labjack_layout = QVBoxLayout(labjack_container)
    labjack_layout.setContentsMargins(5, 5, 5, 5)  # Reduce padding
    labjack_layout.setSpacing(2)  # Reduce spacing between elements

    # Other sensors container
    other_container = QFrame()
    other_container.setFrameShape(QFrame.Shape.Box)
    other_container.setFrameShadow(QFrame.Shadow.Raised)
    other_container.setLineWidth(2)
    other_container.setStyleSheet("""
        QFrame { 
            border: 2px solid #999; 
            border-radius: 8px; 
            background-color: transparent; 
        }
        QFrame:hover { 
            background-color: rgba(200, 200, 200, 0.3); 
            border: 2px solid #777; 
        }
    """)
    other_container.setCursor(Qt.CursorShape.PointingHandCursor)  # Change cursor to hand pointer
    other_layout = QVBoxLayout(other_container)
    other_layout.setContentsMargins(5, 5, 5, 5)  # Reduce padding
    other_layout.setSpacing(2)  # Reduce spacing between elements

    # Add containers to the grid
    devices_status_layout.addWidget(arduino_container, 0, 0)
    devices_status_layout.addWidget(labjack_container, 0, 1)
    devices_status_layout.addWidget(other_container, 0, 2)

    # Arduino content
    arduino_label = QLabel("Arduino")
    arduino_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    arduino_label.setStyleSheet("font-size: 14px; font-weight: bold; border: none; background-color: transparent; margin: 0; padding: 0;")
    arduino_layout.addWidget(arduino_label)

    # Create the arduino image with rounded corners
    arduino_image = QLabel()
    arduino_pixmap = QPixmap(resource_path("app/ui/Arduino.png"))
    arduino_pixmap = arduino_pixmap.scaledToWidth(130, Qt.TransformationMode.SmoothTransformation)

    # Create a mask for rounded corners
    rounded_pixmap = QPixmap(arduino_pixmap.size())
    rounded_pixmap.fill(Qt.GlobalColor.transparent)
    mask_painter = QPainter(rounded_pixmap)
    mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mask_painter.setBrush(Qt.GlobalColor.white)
    mask_painter.setPen(Qt.PenStyle.NoPen)
    mask_painter.drawRoundedRect(rounded_pixmap.rect(), 15, 15)
    mask_painter.end()

    # Apply the mask
    masked_pixmap = QPixmap(arduino_pixmap.size())
    masked_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(masked_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, rounded_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.drawPixmap(0, 0, arduino_pixmap)
    painter.end()

    arduino_image.setPixmap(masked_pixmap)
    arduino_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    arduino_image.setStyleSheet("background-color: transparent; border: none;")
    arduino_layout.addWidget(arduino_image)

    self.arduino_status = QLabel("Not connected")
    self.arduino_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.arduino_status.setStyleSheet("color: grey; font-weight: bold; font-size: 13px; background-color: transparent; border: none; margin: 0; padding: 0;")
    self.arduino_status.setObjectName("arduino_status_label")
    arduino_layout.addWidget(self.arduino_status)

    # Labjack content
    labjack_label = QLabel("Labjack")
    labjack_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    labjack_label.setStyleSheet("font-size: 14px; font-weight: bold; border: none; background-color: transparent; margin: 0; padding: 0;")
    labjack_layout.addWidget(labjack_label)

    # Create the labjack image with rounded corners
    labjack_image = QLabel()
    labjack_pixmap = QPixmap(resource_path("app/ui/Labjack.png"))
    labjack_pixmap = labjack_pixmap.scaledToWidth(130, Qt.TransformationMode.SmoothTransformation)

    # Create and apply the mask for rounded corners (same process as arduino)
    rounded_pixmap = QPixmap(labjack_pixmap.size())
    rounded_pixmap.fill(Qt.GlobalColor.transparent)
    mask_painter = QPainter(rounded_pixmap)
    mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mask_painter.setBrush(Qt.GlobalColor.white)
    mask_painter.setPen(Qt.PenStyle.NoPen)
    mask_painter.drawRoundedRect(rounded_pixmap.rect(), 15, 15)
    mask_painter.end()

    masked_pixmap = QPixmap(labjack_pixmap.size())
    masked_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(masked_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, rounded_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.drawPixmap(0, 0, labjack_pixmap)
    painter.end()

    labjack_image.setPixmap(masked_pixmap)
    labjack_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    labjack_image.setStyleSheet("background-color: transparent; border: none;")
    labjack_layout.addWidget(labjack_image)

    self.labjack_status = QLabel("Not connected")
    self.labjack_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.labjack_status.setStyleSheet("color: grey; font-weight: bold; font-size: 13px; background-color: transparent; border: none; margin: 0; padding: 0;")
    self.labjack_status.setObjectName("labjack_status_label")
    labjack_layout.addWidget(self.labjack_status)

    # Other sensors content
    other_label = QLabel("Other sensors")
    other_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    other_label.setStyleSheet("font-size: 14px; font-weight: bold; border: none; background-color: transparent; margin: 0; padding: 0;")
    other_layout.addWidget(other_label)

    # Create the other sensors image with rounded corners
    other_image = QLabel()
    other_pixmap = QPixmap(resource_path("app/ui/Other.png"))
    other_pixmap = other_pixmap.scaledToWidth(130, Qt.TransformationMode.SmoothTransformation)

    # Create and apply the mask for rounded corners (same process as arduino)
    rounded_pixmap = QPixmap(other_pixmap.size())
    rounded_pixmap.fill(Qt.GlobalColor.transparent)
    mask_painter = QPainter(rounded_pixmap)
    mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mask_painter.setBrush(Qt.GlobalColor.white)
    mask_painter.setPen(Qt.PenStyle.NoPen)
    mask_painter.drawRoundedRect(rounded_pixmap.rect(), 15, 15)
    mask_painter.end()

    masked_pixmap = QPixmap(other_pixmap.size())
    masked_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(masked_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, rounded_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.drawPixmap(0, 0, other_pixmap)
    painter.end()

    other_image.setPixmap(masked_pixmap)
    other_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    other_image.setStyleSheet("background-color: transparent; border: none;")
    other_layout.addWidget(other_image)

    self.other_status = QLabel("Not connected")
    self.other_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.other_status.setStyleSheet("color: grey; font-weight: bold; font-size: 13px; background-color: transparent; border: none; margin: 0; padding: 0;")
    self.other_status.setObjectName("other_status_label")
    other_layout.addWidget(self.other_status)

    # Add click events to open settings tab when clicked
    def open_settings_tab():
        # Find the settings tab index (typically 1)
        settings_tab_index = 1
        self.stacked_widget.setCurrentIndex(settings_tab_index)

    # Open Arduino settings in a popup when Arduino container is clicked
    arduino_container.mousePressEvent = lambda event: self.show_arduino_settings_popup()
    
    # Open LabJack settings in a popup when LabJack container is clicked
    labjack_container.mousePressEvent = lambda event: self.show_labjack_settings_popup()
    
    # Open Other Sensors settings in a popup when Other container is clicked
    other_container.mousePressEvent = lambda event: self.show_other_settings_popup()

    # Set size constraints for the container
    devices_status_container.setFixedHeight(155)  # Further reduced height for the frames

    # Add the device status container to the main layout
    sensors_container_layout.addWidget(devices_status_container, alignment=Qt.AlignmentFlag.AlignHCenter)
    
    # Reduce spacing - use a smaller spacer instead of the larger stretch
    sensors_container_layout.addSpacing(20)  # Increased spacing between device boxes and sensor management
    
    # Create a container widget for the sensor table and controls
    sensor_container = QGroupBox("Sensor Management")
    sensor_container_layout = QVBoxLayout(sensor_container)
    sensor_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    
    # Sensor data table (create this first to calculate width)
    self.data_table = QTableWidget(0, 6)  # Reduced to 6 columns - removed the conversion and port columns
    self.data_table.setHorizontalHeaderLabels(["Show in Graph", "Sensor", "Value", "Interface", "Offset/Unit", "Color"])
    self.data_table.horizontalHeader().setStretchLastSection(True)
    self.data_table.setColumnWidth(0, 100)  # Width for checkbox column
    self.data_table.setColumnWidth(1, 120)  # Sensor name
    self.data_table.setColumnWidth(2, 100)  # Value
    self.data_table.setColumnWidth(3, 80)   # Interface
    self.data_table.setColumnWidth(4, 100)  # Offset/Unit
    self.data_table.setColumnWidth(5, 80)   # Color
    
    # Set a fixed width for the table based on the sum of column widths plus some margin
    table_width = sum([self.data_table.columnWidth(i) for i in range(6)]) + 30  # Add margin for scrollbar
    self.data_table.setMinimumWidth(table_width)
    self.data_table.setMaximumWidth(table_width)
    
    # Set a minimum height for the table to show about 15 rows
    row_height = self.data_table.verticalHeader().defaultSectionSize()
    header_height = self.data_table.horizontalHeader().height()
    self.data_table.setMinimumHeight(row_height * 15 + header_height)
    self.data_table.setObjectName("data_table")  # Set object name for findChild
    
    # Add row selection behavior to enable edit/remove buttons when a row is selected
    self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    self.data_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    
    # Sensor management - buttons with width matching the table
    sensor_controls = QHBoxLayout()
    self.add_sensor_btn = QPushButton("Add Sensor")
    self.add_sensor_btn.setObjectName("add_sensor_btn")  # Set object name for findChild
    self.edit_sensor_btn = QPushButton("Edit Sensor")
    self.edit_sensor_btn.setObjectName("edit_sensor_btn")  # Set object name for findChild
    self.remove_sensor_btn = QPushButton("Remove Sensor")
    self.remove_sensor_btn.setObjectName("remove_sensor_btn")  # Set object name for findChild
    
    # Set fixed width for buttons to make them equal and fit within table width
    button_width = (table_width - 20) // 3  # Divide table width by 3 with small gaps
    self.add_sensor_btn.setFixedWidth(button_width)
    self.add_sensor_btn.setStyleSheet(green_button_style)
    self.edit_sensor_btn.setFixedWidth(button_width)
    # Don't disable the edit button initially
    self.remove_sensor_btn.setFixedWidth(button_width)
    # Don't disable the remove button initially
    
    # Remove these connections - they will be handled by the controller
    # self.add_sensor_btn.clicked.connect(self.add_sensor)
    # self.edit_sensor_btn.clicked.connect(self.edit_sensor)
    # self.remove_sensor_btn.clicked.connect(self.remove_sensor)
    sensor_controls.addWidget(self.add_sensor_btn)
    sensor_controls.addWidget(self.edit_sensor_btn)
    sensor_controls.addWidget(self.remove_sensor_btn)
    sensor_controls.setSpacing(10)  # Add spacing between buttons
    sensor_controls.addStretch()  # Add stretch to keep buttons aligned left
    
    # Add controls and table to the container
    sensor_container_layout.addLayout(sensor_controls)
    sensor_container_layout.addWidget(self.data_table)
    
    # Connect table selection to enable buttons
    self.data_table.cellClicked.connect(self.select_sensor)
    
    # Add the sensor container to the main layout with horizontal centering
    sensors_container_layout.addWidget(sensor_container, alignment=Qt.AlignmentFlag.AlignHCenter)
    
    # Add a small spacing after the group box
    sensors_container_layout.addSpacing(5)
    
    # Add explanation text about "Show in Graph" checkbox - below the Sensor Management group box
    explanation_label = QLabel("Note: The 'Show in Graph' checkbox only controls whether a sensor appears in graph visualizations. All enabled sensors have their data recorded regardless of this setting.")
    explanation_label.setStyleSheet("color: #666; font-style: italic;")
    explanation_label.setWordWrap(True)
    explanation_label.setMinimumWidth(table_width)  # Set minimum width to match table
    explanation_label.setMaximumWidth(table_width)  # Set maximum width to match table
    explanation_label.setMinimumHeight(40)  # Set minimum height to ensure two lines are visible
    explanation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sensors_container_layout.addWidget(explanation_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    
    # Add stretch to push everything up
    sensors_container_layout.addStretch(1)  # Add stretch after the container with equal weight
    
    # Add sensors tab
    self.stacked_widget.addWidget(sensors_tab)
    
    # Create Graphs Tab
    graphs_tab = QWidget()
    graphs_layout = QVBoxLayout(graphs_tab)
    
    # Create a splitter for the graphs tab
    graphs_splitter = QSplitter(Qt.Orientation.Horizontal)
    graphs_layout.addWidget(graphs_splitter)
    
    # Left side - Graph controls and info
    graph_controls_widget = QWidget()
    graph_controls_layout = QVBoxLayout(graph_controls_widget)
    graph_controls_widget.setMinimumWidth(300)
    graph_controls_widget.setMaximumWidth(400)
    
    # Graph type selection
    graph_type_group = QGroupBox("Graph Type")
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
    
    # Graph info area
    graph_info_text = QTextEdit()
    graph_info_text.setReadOnly(True)
    graph_info_text.setMinimumHeight(200)
    graph_info_text.setStyleSheet("background-color: #f0f0f0; color: #333333; border-radius: 5px; padding: 10px;")
    graph_info_text.setHtml("""
    <h3>Graph Types</h3>
    <p><b>Standard Time Series:</b> Shows raw sensor values over time. Basic visualization for all experiments. You can select multiple sensors to compare their behavior simultaneously.</p>
    <p><b>Temperature Difference:</b> Shows the difference between two measurement points over time. Useful for identifying heat transfer or temperature gradients.</p>
    <p><b>Rate of Change (dT/dt):</b> Shows the rate of temperature change. Helps identify thermal response times or sudden changes (e.g., exothermic or endothermic processes).</p>
    <p><b>Moving Average:</b> Shows the moving average over a specific time period. Reduces noise and helps identify trends more clearly.</p>
    <p><b>Fourier Analysis:</b> Shows periodic components in the temperature data. Can help discover oscillations or cyclical patterns.</p>
    <p><b>Histogram:</b> Shows the distribution of measured values - how often each value or range of values occurs.</p>
    <p><b>Box Plot:</b> Shows the distribution of measured values using quartiles.</p>
    <p><b>Correlation Analysis:</b> If you have multiple sensors, a correlation graph shows whether and how strongly different measurement points are related. Important for experiments with spatial temperature distribution.</p>
    """)
    graph_type_layout.addWidget(graph_info_text)
    
    # Connect graph type combo to update info text
    def update_graph_info():
        graph_type = self.graph_type_combo.currentText()
        if graph_type == "Standard Time Series":
            graph_info_text.setHtml("""
            <h3>Standard Time Series</h3>
            <p>The most basic and versatile graph type showing raw sensor values plotted against time.</p>
            <p><b>When to use:</b> This is the default visualization for most experiments. Use it to get a quick overview of your data and to identify general trends, peaks, and valleys.</p>
            <p><b>Interpretation:</b> The x-axis represents time, while the y-axis shows the measured values. Rising lines indicate increasing values, falling lines indicate decreasing values.</p>
            <p><b>Tip:</b> You can select multiple sensors to compare their behavior over time. Use the primary sensor dropdown to select the main sensor, and the additional sensors list below to select multiple sensors to display simultaneously.</p>
            """)
        elif graph_type == "Temperature Difference":
            graph_info_text.setHtml("""
            <h3>Temperature Difference Graph</h3>
            <p>Shows the difference between two measurement points or locations over time.</p>
            <p><b>When to use:</b> When you want to analyze heat transfer, temperature gradients, or the relative behavior of two sensors.</p>
            <p><b>Interpretation:</b> The y-axis shows the temperature difference (T₁-T₂). Positive values mean the first sensor is warmer, negative values mean the second sensor is warmer.</p>
            <p><b>Tip:</b> This is particularly useful for experiments involving heat flow or thermal conductivity.</p>
            """)
        elif graph_type == "Rate of Change (dT/dt)":
            graph_info_text.setHtml("""
            <h3>Rate of Change (dT/dt)</h3>
            <p>Shows how quickly the measured value is changing at each point in time.</p>
            <p><b>When to use:</b> When you're interested in the speed of changes rather than absolute values. Useful for identifying reaction rates, thermal response times, or sudden events.</p>
            <p><b>Interpretation:</b> The y-axis shows the rate of change. Positive values indicate rising temperatures, negative values indicate falling temperatures. Steeper slopes mean faster changes.</p>
            <p><b>Tip:</b> Look for sudden spikes that might indicate exothermic or endothermic reactions.</p>
            """)
        elif graph_type == "Moving Average":
            graph_info_text.setHtml("""
            <h3>Moving Average</h3>
            <p>Shows the average value over a sliding window of time, smoothing out short-term fluctuations.</p>
            <p><b>When to use:</b> When your data contains noise or rapid fluctuations that make it difficult to see the underlying trend.</p>
            <p><b>Interpretation:</b> The smoother line represents the average trend, filtering out random variations and noise.</p>
            <p><b>Tip:</b> You can adjust the window size to control the amount of smoothing. Larger windows give smoother lines but might miss important short-term changes.</p>
            """)
        elif graph_type == "Fourier Analysis":
            graph_info_text.setHtml("""
            <h3>Fourier Analysis (Spectral Analysis)</h3>
            <p>Transforms time-domain data into the frequency domain to reveal periodic components.</p>
            <p><b>When to use:</b> When you suspect your data contains cyclical patterns or oscillations that might not be obvious in the time domain.</p>
            <p><b>Interpretation:</b> The x-axis shows frequency, while the y-axis shows the strength of each frequency component. Peaks indicate strong periodic behavior at that frequency.</p>
            <p><b>Tip:</b> This is an advanced analysis technique particularly useful for identifying hidden patterns or resonances in your experimental system.</p>
            """)
        elif graph_type == "Histogram":
            graph_info_text.setHtml("""
            <h3>Histogram</h3>
            <p>Shows the distribution of measured values - how often each value or range of values occurs.</p>
            <p><b>When to use:</b> When you want to understand the statistical distribution of your data or identify the most common values.</p>
            <p><b>Interpretation:</b> The x-axis shows the value ranges (bins), while the y-axis shows how many measurements fall into each bin. Tall bars indicate commonly occurring values.</p>
            <p><b>Tip:</b> Look for multiple peaks that might indicate different stable states in your system.</p>
            """)
        elif graph_type == "Box Plot":
            graph_info_text.setHtml("""
            <h3>Box Plot (Box-and-Whisker)</h3>
            <p>Shows the distribution of measured values using quartiles.</p>
            <p><b>When to use:</b> When you want a statistical summary of your data, including median, spread (interquartile range), and potential outliers.</p>
            <p><b>Interpretation:</b> The box spans the interquartile range (IQR: 25th to 75th percentile). The line inside is the median (50th percentile). Whiskers typically extend to 1.5 times the IQR from the box, or to the data extremes if closer. Points outside the whiskers are potential outliers.</p>
            <p><b>Tip:</b> Useful for comparing distributions across different sensors or time periods (if implemented) or identifying skewed data.</p>
            """)
        elif graph_type == "Correlation Analysis":
            graph_info_text.setHtml("""
            <h3>Correlation Analysis</h3>
            <p>Shows how strongly two variables are related to each other.</p>
            <p><b>When to use:</b> When you have multiple sensors and want to understand how they influence each other or respond to the same stimuli.</p>
            <p><b>Interpretation:</b> Points forming a diagonal line indicate strong correlation. Scattered points indicate weak or no correlation. The correlation coefficient (r) quantifies this relationship.</p>
            <p><b>Tip:</b> This can help identify cause-and-effect relationships or dependencies between different parts of your experimental setup.</p>
            """)
    
    self.graph_type_combo.currentIndexChanged.connect(update_graph_info)
    
    # Sensor selection
    sensor_selection_group = QGroupBox("Sensor Selection")
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
    
    # Plot Format Settings
    plot_format_group = QGroupBox("Plot Format")
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
    # Set Dark as the default preset
    self.plot_style_preset.setCurrentIndex(2)  # "Dark" is at index 2
    
    # Connect to the apply_plot_formatting function and then update graphs
    self.plot_style_preset.currentIndexChanged.connect(lambda: [
        self.apply_plot_formatting(),
        self.update_graph(),
        self.update_dashboard_graph() if hasattr(self, 'dashboard_graph_widget') else None
    ])
    
    plot_format_layout.addWidget(self.plot_style_preset, 0, 1)
    
    # Font size
    plot_format_layout.addWidget(QLabel("Font Size:"), 1, 0)
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
    
    plot_format_layout.addWidget(self.plot_font_size, 1, 1)
    
    # Line size
    plot_format_layout.addWidget(QLabel("Line Width:"), 2, 0)
    self.plot_line_width = QSpinBox()
    self.plot_line_width.setRange(1, 10)
    self.plot_line_width.setValue(2)
    self.plot_line_width.setSuffix(" px")
    
    # Connect to the apply_plot_formatting function and then update graphs
    self.plot_line_width.valueChanged.connect(lambda: [
        self.apply_plot_formatting(),
        self.update_graph(),
        self.update_dashboard_graph() if hasattr(self, 'dashboard_graph_widget') else None
    ])
    
    plot_format_layout.addWidget(self.plot_line_width, 2, 1)
    
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
    self.graph_widget.setBackground('#2D2D2D')
    self.graph_widget.getAxis('bottom').setPen('#BBBBBB')
    self.graph_widget.getAxis('left').setPen('#BBBBBB')
    self.graph_widget.getAxis('bottom').setTextPen('#EEEEEE')
    self.graph_widget.getAxis('left').setTextPen('#EEEEEE')
    self.graph_widget.showGrid(x=True, y=True, alpha=0.2)
    self.graph_widget.setLabel('left', 'Value')
    self.graph_widget.setLabel('bottom', 'Sample Count')
    self.graph_widget.addLegend()
    graph_display_layout.addWidget(self.graph_widget)
    
    # Add widgets to splitter
    graphs_splitter.addWidget(graph_controls_widget)
    graphs_splitter.addWidget(graph_display_widget)
    graphs_splitter.setSizes([400, 800])  # Initial sizes
    
    # Add graphs tab to stacked widget
    self.stacked_widget.addWidget(graphs_tab)
    
    # Create Automation Tab
    automation_tab = QWidget()
    automation_layout = QVBoxLayout(automation_tab)
    
    # Create a fixed-width container for automation content
    automation_container = QWidget()
    automation_container.setFixedWidth(800)  # Set a reasonable fixed width
    automation_container_layout = QVBoxLayout(automation_container)
    automation_container_layout.setContentsMargins(0, 0, 0, 0)
    
    # Center the container in the tab
    automation_layout.addWidget(automation_container, 0, Qt.AlignmentFlag.AlignCenter)
    
    # Description label
    automation_description = QLabel("Automate your experiment by defining triggers and actions. "
                                    "Triggers can be time-based, sensor-based, or event-based. "
                                    "Actions can include sending commands to Arduino, LabJack, or other connected devices.")
    automation_description.setWordWrap(True)
    automation_container_layout.addWidget(automation_description)
    
    # Automation sequences section
    automation_sequences_group = QGroupBox("Automation Sequences")
    automation_sequences_layout = QVBoxLayout(automation_sequences_group)
    
    # Table to display defined automation sequences
    self.sequences_table = QTableWidget()
    self.sequences_table.setColumnCount(3)
    self.sequences_table.setHorizontalHeaderLabels(["Name", "Status", "Actions"])
    self.sequences_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    self.sequences_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.sequences_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.sequences_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
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
    automation_container_layout.addWidget(automation_sequences_group)
    
    # Help section
    automation_help_group = QGroupBox("Automation Help & Documentation")
    automation_help_layout = QVBoxLayout(automation_help_group)
    
    automation_help_text = QTextEdit()
    automation_help_text.setReadOnly(True)
    # Reduced height to give more space to the sequences table
    automation_help_text.setMinimumHeight(200)
    
    # Set documentation text
    help_text = """
    <h2>Automation Help</h2>
    <p>This tab allows you to create automation sequences that trigger actions when specific conditions are met.</p>
    
    <h3>Creating Sequences</h3>
    <ol>
        <li>Click "New Sequence" to create a new automation sequence</li>
        <li>Give your sequence a descriptive name</li>
        <li>Add steps to your sequence using the Add Step button</li>
        <li>Configure the trigger conditions and actions for each step</li>
        <li>Save your sequence</li>
    </ol>
    
    <h3>Types of Triggers</h3>
    <ul>
        <li><strong>Time-based:</strong> Trigger after a specific time interval or at a specific time</li>
        <li><strong>Sensor-based:</strong> Trigger when a sensor value crosses a threshold</li>
        <li><strong>Event-based:</strong> Trigger when a specific event occurs (button press, recording start/stop)</li>
    </ul>
    
    <h3>Available Actions</h3>
    <ul>
        <li><strong>Arduino commands:</strong> Send commands to connected Arduino devices</li>
        <li><strong>LabJack operations:</strong> Control LabJack outputs or read inputs</li>
        <li><strong>Camera operations:</strong> Take snapshots, start/stop recording</li>
        <li><strong>System actions:</strong> Play sounds, show alerts, log messages</li>
    </ul>
    
    <h3>Running Sequences</h3>
    <p>Select a sequence in the table and click "Run Sequence" to start it. The sequence will run until stopped manually or until it completes all steps.</p>
    """
    automation_help_text.setHtml(help_text)
    automation_help_layout.addWidget(automation_help_text)
    automation_container_layout.addWidget(automation_help_group)
    
    # Time-lapse Video Creation section
    timelapse_group = QGroupBox("Time-lapse Video Creation")
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
    
    # Add timelapse group to the automation container
    automation_container_layout.addWidget(timelapse_group)
    
    # Add automation tab to stacked widget
    self.stacked_widget.addWidget(automation_tab)
    
    # Create Settings Tab
    settings_tab = QWidget()
    settings_layout = QVBoxLayout(settings_tab)
    
    # Create a horizontal layout for the two columns with less spacing
    settings_columns_layout = QHBoxLayout()
    settings_columns_layout.setSpacing(20)  # Reduce spacing between columns
    settings_columns_layout.setContentsMargins(20, 50, 20, 50)  # Add vertical padding to center content
    
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
    self.arduino_poll_interval.setValue(float(self.settings.value("arduino_poll_interval", "1.0")))
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
    
    self.ndi_source_name = QLineEdit(self.settings.value("ndi_source_name", "EvoLabs DAQ"))
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
    
    # Add settings tab to stacked widget
    self.stacked_widget.addWidget(settings_tab)
    
    # Add Projects Tab
    projects_tab = QWidget()
    projects_tab.setObjectName("projects_tab")
    projects_layout = QVBoxLayout(projects_tab)
    
    # Create a fixed-width container for project content
    project_container = QWidget()
    project_container.setFixedWidth(980)  # Increased width for better layout and to move content left
    project_container_layout = QVBoxLayout(project_container)
    project_container_layout.setContentsMargins(10, 20, 10, 20)  # Reduced left/right margin to move content left
    project_container_layout.setSpacing(15)  # Increase spacing between elements
    
    # Center the container in the tab
    projects_layout.addWidget(project_container, 0, Qt.AlignmentFlag.AlignCenter)
    
    # Description label
    project_description = QLabel("Manage your data collection projects, test series, and runs. "
                                "Each run will be saved with a timestamp and all relevant settings.")
    project_description.setWordWrap(True)
    project_container_layout.addWidget(project_description)
    
    # Create a horizontal layout for the main content
    main_content_layout = QHBoxLayout()
    main_content_layout.setSpacing(30)  # Reduce spacing between columns (was 40)
    
    # Left column for project structure
    left_column_layout = QVBoxLayout()
    left_column_layout.setSpacing(15)  # Increased spacing
    
    # Project section (directly in left column, no outer groupbox)
    project_group = QGroupBox("Project")
    project_group_layout = QVBoxLayout(project_group)
    project_group_layout.setSpacing(10)
    
    # Store reference to the group box in the main window
    self.project_group = project_group
    
    # Set slightly larger font for groups
    sub_font = project_group.font()
    sub_font.setPointSize(11)
    sub_font.setBold(True)
    project_group.setFont(sub_font)
    
    # Set custom border style
    project_group.setStyleSheet("QGroupBox { border: 2px solid #FFA500; border-radius: 5px; padding-top: 15px; margin-top: 10px; }")
    
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
    project_desc_layout.addWidget(project_desc_label)
    self.project_description = QTextEdit()
    self.project_description.setMaximumHeight(80)
    self.project_description.setPlaceholderText("Enter a description for this project")
    project_desc_layout.addWidget(self.project_description)
    project_group_layout.addLayout(project_desc_layout)
    
    # Add project group directly to left column
    left_column_layout.addWidget(project_group)
    
    # Test Series section
    test_series_group = QGroupBox("Test Series")
    test_series_group_layout = QVBoxLayout(test_series_group)
    test_series_group_layout.setSpacing(10)
    
    # Store reference to the group box in the main window
    self.test_series_group = test_series_group
    
    # Set slightly larger font for groups
    test_series_group.setFont(sub_font)  # Reuse the same font
    
    # Set custom border style
    test_series_group.setStyleSheet("QGroupBox { border: 2px solid #FFA500; border-radius: 5px; padding-top: 15px; margin-top: 10px; }")
    
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
    test_series_desc_layout.addWidget(test_series_desc_label)
    self.test_series_description = QTextEdit()
    self.test_series_description.setMaximumHeight(80)
    self.test_series_description.setPlaceholderText("Enter a description for this test series")
    test_series_desc_layout.addWidget(self.test_series_description)
    test_series_group_layout.addLayout(test_series_desc_layout)
    
    # Add test series group directly to left column
    left_column_layout.addWidget(test_series_group)
    
    # Run section
    run_group = QGroupBox("Run")
    run_group_layout = QVBoxLayout(run_group)
    run_group_layout.setSpacing(10)
    
    # Store reference to the group box in the main window
    self.run_group = run_group
    
    # Set slightly larger font for groups
    run_group.setFont(sub_font)  # Reuse the same font
    
    # Set custom border style
    run_group.setStyleSheet("QGroupBox { border: 2px solid #FFA500; border-radius: 5px; padding-top: 15px; margin-top: 10px; }")
    
    # Sampling rate setting
    sampling_rate_layout = QHBoxLayout()
    sampling_rate_layout.setSpacing(8)
    sampling_rate_label = QLabel("Sampling Interval:")
    sampling_rate_label.setMinimumWidth(100)
    sampling_rate_layout.addWidget(sampling_rate_label)
    
    self.sampling_rate_spinbox = QDoubleSpinBox()
    self.sampling_rate_spinbox.setRange(0.001, 9999)
    self.sampling_rate_spinbox.setValue(1.0)  # Default 1 second
    self.sampling_rate_spinbox.setDecimals(3)  # Allow millisecond precision
    self.sampling_rate_spinbox.setSingleStep(0.1)  # Step by 0.1 seconds
    self.sampling_rate_spinbox.setToolTip("Global sampling interval for all sensors (seconds)")
    sampling_rate_layout.addWidget(self.sampling_rate_spinbox)
    
    sampling_rate_unit = QLabel("seconds")
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
    run_desc_layout.addWidget(run_desc_label)
    self.run_description = QTextEdit()
    self.run_description.setMaximumHeight(80)
    self.run_description.setPlaceholderText("Enter a description for this run")
    run_desc_layout.addWidget(self.run_description)
    run_group_layout.addLayout(run_desc_layout)
    
    # Add run group directly to left column
    left_column_layout.addWidget(run_group)
    
    # Project actions section
    project_actions_group = QGroupBox("Actions")
    project_actions_layout = QHBoxLayout(project_actions_group)
    project_actions_layout.setSpacing(10)
    project_actions_layout.setContentsMargins(15, 15, 15, 15)
    project_actions_group.setFont(sub_font)  # Reuse the same font
    
    # Export project button (renamed from Save Project)
    self.save_project_btn = QPushButton("Export Data")
    self.save_project_btn.setIcon(QIcon.fromTheme("document-save"))
    self.save_project_btn.setMinimumWidth(120)
    project_actions_layout.addWidget(self.save_project_btn)
    
    # Load project button
    self.load_project_btn = QPushButton("Load Run")
    self.load_project_btn.setIcon(QIcon.fromTheme("document-open"))
    self.load_project_btn.setMinimumWidth(120)
    project_actions_layout.addWidget(self.load_project_btn)
    
    # Apply Settings Button for interface settings
    self.apply_settings_btn = QPushButton("Apply Interface Settings")
    self.apply_settings_btn.setIcon(QIcon.fromTheme("preferences-system"))
    self.apply_settings_btn.setMinimumWidth(120)
    self.apply_settings_btn.clicked.connect(self.apply_settings)
    project_actions_layout.addWidget(self.apply_settings_btn)
    
    # Add left column to main content layout
    main_content_layout.addLayout(left_column_layout)
    
    # Right column for project browser
    right_column_layout = QVBoxLayout()
    right_column_layout.setContentsMargins(0, 0, 0, 0)  # Remove extra margins to move left
    
    # Project browser section
    project_browser_group = QGroupBox("Project Browser")
    project_browser_group.setMinimumWidth(520)  # Reduced width from 550 to 520
    project_browser_layout = QVBoxLayout(project_browser_group)
    project_browser_layout.setContentsMargins(10, 15, 10, 15)  # Reduce left/right margins
    
    # Set larger font for the title
    browser_font = project_browser_group.font()
    browser_font.setPointSize(12)
    browser_font.setBold(True)
    project_browser_group.setFont(browser_font)
    
    # Project tree view
    self.project_tree = QTreeView()
    self.project_tree.setMinimumHeight(400)  # Increased height to match left column
    # Make the tree view read-only by disabling edit triggers
    self.project_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    # Ensure selection remains visible and active even when focus is lost
    self.project_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    self.project_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    # Set strong focus to maintain selection when focus is lost
    self.project_tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    # Keep selection highlight even when the tree loses focus
    self.project_tree.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
    self.project_model = QStandardItemModel()
    self.project_model.setHorizontalHeaderLabels(["Name", "Description", "Date"])
    self.project_tree.setModel(self.project_model)
    self.project_tree.setColumnWidth(0, 200)
    self.project_tree.setColumnWidth(1, 270)  # Reduce Description column
    self.project_tree.setColumnWidth(2, 120)  # Increase Date column width
    self.project_tree.setAlternatingRowColors(True)
    project_browser_layout.addWidget(self.project_tree)
    
    # Add the Actions group at the bottom of the Project Browser
    project_browser_layout.addWidget(project_actions_group)
    
    # Add project browser group to right column
    right_column_layout.addWidget(project_browser_group)
    
    # Add right column to main content layout
    main_content_layout.addLayout(right_column_layout)
    
    # Add main content layout to container
    project_container_layout.addLayout(main_content_layout)
    
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
    
    # Add the video tab to the stacked widget (no button, will be accessed differently)
    self.stacked_widget.addWidget(video_tab)
    
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
    set_large_font_for_groupbox(automation_help_group)
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
    notes_layout = QVBoxLayout(notes_tab)
    notes_layout.setContentsMargins(10, 10, 10, 10)
    notes_layout.setSpacing(0)  # Reduce spacing between elements
    
    # HTML editor with improved styling
    notes_text_edit = QTextEdit()
    notes_text_edit.setAcceptRichText(True)
    notes_text_edit.setStyleSheet("""
        QTextEdit {
            font-size: 14px; 
            background: #222; 
            color: #eee; 
            border-radius: 6px; 
            padding: 8px;
            border: 1px solid #444;
        }
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

def update_focus_value_label(self):
    """Update the focus value label when the slider changes"""
    value = self.camera_tab_focus_slider.value()
    self.camera_tab_focus_value.setText(str(value))
    
def update_exposure_value_label(self):
    """Update the exposure value label when the slider changes"""
    value = self.camera_tab_exposure_slider.value()
    self.camera_tab_exposure_value.setText(str(value))
    
def apply_camera_focus_exposure(self):
    """Apply camera focus and exposure settings"""
    # Only process if camera is connected
    if not hasattr(self, 'camera_controller') or not self.camera_controller.is_connected:
        return
        
    try:
        # Get focus and exposure settings from the camera tab controls
        manual_focus = self.camera_tab_manual_focus.isChecked()
        focus_value = self.camera_tab_focus_slider.value()
        manual_exposure = self.camera_tab_manual_exposure.isChecked()
        exposure_value = self.camera_tab_exposure_slider.value()
        
        # Update slider enabled states
        self.camera_tab_focus_slider.setEnabled(manual_focus)
        self.camera_tab_exposure_slider.setEnabled(manual_exposure)
        
        # Save to settings
        self.settings.set_value("camera/manual_focus", "true" if manual_focus else "false")
        self.settings.set_value("camera/focus_value", str(focus_value))
        self.settings.set_value("camera/manual_exposure", "true" if manual_exposure else "false")
        self.settings.set_value("camera/exposure_value", str(exposure_value))
        
        # Apply settings to camera directly
        if self.camera_controller and self.camera_controller.camera_thread:
            if hasattr(self.camera_controller.camera_thread, 'set_camera_properties'):
                self.camera_controller.camera_thread.set_camera_properties(
                    manual_focus=manual_focus,
                    focus_value=focus_value,
                    manual_exposure=manual_exposure,
                    exposure_value=exposure_value
                )
            else:
                # Fallback for direct camera manipulation
                if hasattr(self.camera_controller.camera_thread, 'cap') and self.camera_controller.camera_thread.cap:
                    if manual_focus:
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # Disable autofocus
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_FOCUS, focus_value)
                    else:
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # Enable autofocus
                    
                    if manual_exposure:
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Magic value for manual
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_EXPOSURE, exposure_value)
                    else:
                        self.camera_controller.camera_thread.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Magic value for auto
            
    except Exception as e:
        print(f"Error applying camera focus/exposure: {str(e)}")
        import traceback
        traceback.print_exc()

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
    
    # Define frame styles
    connected_frame_style = """
        QFrame { 
            border: 2px solid #009900; 
            border-radius: 8px; 
            background-color: rgba(0, 153, 0, 0.1); 
        }
        QFrame:hover { 
            background-color: rgba(0, 153, 0, 0.2); 
            border: 2px solid #00bb00; 
        }
    """
    
    disconnected_frame_style = """
        QFrame { 
            border: 2px solid #999; 
            border-radius: 8px; 
            background-color: transparent; 
        }
        QFrame:hover { 
            background-color: rgba(200, 200, 200, 0.3); 
            border: 2px solid #777; 
        }
    """
    
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
                    frame_style = connected_frame_style if is_connected else disconnected_frame_style
                    arduino_container.setStyleSheet(frame_style)
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
                    frame_style = connected_frame_style if is_connected else disconnected_frame_style
                    labjack_container.setStyleSheet(frame_style)
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
                    frame_style = connected_frame_style if is_connected else disconnected_frame_style
                    other_container.setStyleSheet(frame_style)
                    
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
        # Get settings from the camera tab
        camera_id = self.camera_id.currentIndex()
        
        # Get resolution and framerate from settings instead of UI elements (which were removed)
        resolution = self.settings.value("camera/resolution", "1280x720")
        fps = int(self.settings.value("camera/fps", "30"))
        
        # Update the settings values
        self.settings.set_value("camera/default_camera", str(camera_id))
        
        # Connect to the camera
        self.camera_controller.toggle_camera()
        
        # Apply focus and exposure settings after connection
        if self.camera_controller.is_connected:
            self.apply_camera_focus_exposure()
    else:
        # Disconnect the camera
        self.camera_controller.toggle_camera()


