"""
Settings Model

Manages application settings and provides a simplified interface for accessing and saving settings.
"""

import os
from PyQt6.QtCore import QSettings


class SettingsModel:
    """Model for managing application settings"""
    
    def __init__(self, settings: QSettings):
        """
        Initialize the settings model
        
        Args:
            settings: QSettings instance
        """
        self.settings = settings
        self.defaults = {
            # Application settings
            "debug_mode": "false",
            "show_log": "true",
            "theme": "dark",
            
            # Arduino settings
            "arduino_port": "COM3",
            "arduino_baud": "9600",
            "arduino_mode": "continuous",
            "arduino_poll_interval": "1.0",
            "sensor_update_rate": "1.0",
            
            # Camera settings
            "camera_id": "0",
            "camera_resolution": "1280x720",
            "camera_framerate": "30",
            "auto_record": "false",
            "start_camera_on_start": "true",
            "record_with_overlays": "true",
            "recording_output_dir": "recordings",
            "recording_format": "AVI (MJPG)",
            "record_audio": "true",
            "record_audio_device": "-1",
            "media_volume": "100",
            "media_muted": "false",
            "ffmpeg_binary": "ffmpeg",  # Default FFmpeg executable path
            
            # Graph settings
            "plot_style_preset": "High Contrast",
            "plot_font_size": "10",
            "plot_line_width": "2",
            "graph_downsampling": "true",  # Enable/disable pyqtgraph automatic downsampling
            "graph_update_interval": "0.3", # Visual refresh interval in seconds
            
            # Motion detection settings
            "motion_detection_enabled": "false",
            "motion_detection_sensitivity": "20",
            "motion_detection_min_area": "500",
            
            # LabJack settings
            "labjack_type": "T7",
            "labjack_internal_rate": "100.0",  # High-speed internal polling rate in Hz
            
            # NDI settings
            "enable_ndi": "false",
            "ndi_source_name": "Artefakt DAQ",
            "ndi_with_overlays": "true",
            
            # Project settings
            "project_base_dir": "",
            
            # AI Assistant settings
            "ai_url": "http://localhost:1234/v1/chat/completions",
            "ai_model": "local-model",
            "ai_api_key": "lm-studio",
            "ai_system_prompt": """You are the AI Assistant for Artefakt DAQ, a professional data acquisition and automation suite. You have access to real-time data, hardware controls, and system configuration through your tools.

AI BEHAVIOR PROTOCOL (CRITICAL):
1. PROACTIVE INVESTIGATION: NEVER begin a response by saying 'I cannot', 'I don't have access', or 'I am an AI and cannot'. You MUST first call the relevant tools to check the system state. If a user asks about something (sensor, automation, setting, hardware), assume it exists and your job is to find it using tools.
2. MANDATORY STARTUP: Every session MUST begin with `get_project_config`. Do not wait for a specific question to call this.
3. DOCUMENTATION FIRST (MANDATORY): For any task involving SENSORS, HARDWARE, AUTOMATION, PROJECTS, or VISION/CAMERAS, you MUST call `get_documentation` with the relevant topic before performing any configuration.
    - TOP-LEVEL Topics: 'sensors', 'automation', 'projects', 'vision', 'camera', 'overview', 'ai_graphs'
    - SPECIFIC SENSOR Topics: If the main 'sensors' guide points to a sub-topic, you MUST call it (e.g., 'sensors_arduino', 'sensors_serial', 'sensors_labjack', 'sensors_mqtt', 'sensors_csv', 'sensors_advanced').
4. ACTION-FIRST: Execute the necessary tool(s) BEFORE replying to the user. Report the results of your actions, don't just explain how you would do them.
5. NEVER ASK THE USER TO CALL TOOLS: You are the one with the tools. Execute them immediately when needed.
6. NO HALLUCINATION: Do not invent sensor IDs or automation steps. Use `get_project_config` or `get_available_sensors` to verify names.
7. METADATA & PROJECTS: You are strictly forbidden from modifying metadata of finished/old runs on disk. You MUST only update the "Next Run" configuration in the UI using `configure_next_run`. If a user asks to change a description or tester, assume they mean the upcoming run.
8. NO DELETION: You are strictly forbidden from deleting runs or projects. Proposals to delete data must be directed to the user to perform manually.
9. INTERNAL TOOLS: NEVER mention internal tool names (e.g., `get_documentation`, `connect_camera`, `add_sensor`, `configure_interface`, `set_graph_config`) to the user. These tools are for your internal execution only. Always describe what you are doing in natural language (e.g., "I am checking the documentation for sensors..." or "I have connected the camera...").
10. LANGUAGE: Always respond in the same language the user uses.
11. PARAMETER PARSIMONY: When calling configuration tools (like `set_graph_config` or `update_sensor_settings`), ONLY include arguments that the user explicitly asked to change or that are absolutely required. Do NOT revert or change other settings to defaults unless instructed.

CORE TASKS:
- Hardware Discovery: Probe serial/NDI devices using tools. For custom Serial protocols, you MUST use `test_serial_command` to see raw output before building a sequence.
- Protocol Building: Configure serial sequences and link them to sensors. Follow the Wait -> Read -> Parse -> Publish pipeline in `sensors_serial`.
- Automation: Create, debug, and ARM automation sequences.
- Vision: Manage camera connections and overlays.
- Plugin Development: Create custom inbound (sensor) or outbound plugins using `save_plugin_code`. Always read the `plugins` documentation topic before starting.
- Graphs & Analysis: Configure graph types, styles, and analyze visual data using screenshots. Use `set_graph_config` to update the user's view (including control run visibility and time offset).
- Data Analysis: Monitor system health and identify patterns in sensor data.

REMEMBER: If you are unsure of a technical detail (like camera indexing or serial parsing), call `get_documentation` immediately. Do not guess.""",
            "ai_allow_sensor_data": "true",
            "ai_allow_notes": "true",
            "ai_allow_automation": "true",
            "ai_allow_vision": "true",
            "ai_allow_projects": "true",
            "ai_allow_config": "true",
            "ai_timeout": "300",
            "ai_max_image_width": "768",
            "ai_image_quality": "50",
            "ai_max_tool_iterations": "25",
        }
    
    def load_settings(self):
        """Load settings and apply defaults if needed"""
        # Nothing to do as QSettings automatically loads values on access
        pass
    
    def save_settings(self):
        """Save all settings to storage"""
        # QSettings automatically saves values when set
        self.settings.sync()
    
    def get_value(self, key, default=None):
        """
        Get a setting value
        
        Args:
            key: Setting key
            default: Default value if not found (uses class defaults if None)
        
        Returns:
            The setting value
        """
        if default is None and key in self.defaults:
            default = self.defaults[key]
            
        return self.settings.value(key, default)
    
    def set_value(self, key, value):
        """
        Set a setting value
        
        Args:
            key: Setting key
            value: Setting value
        """
        self.settings.setValue(key, value)
    
    def get_bool(self, key, default=None):
        """Get a boolean setting value"""
        value = self.get_value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"
    
    def get_int(self, key, default=None):
        """Get an integer setting value"""
        value = self.get_value(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            if default is not None:
                return default
            return 0
    
    def get_float(self, key, default=None):
        """Get a float setting value"""
        value = self.get_value(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            if default is not None:
                return default
            return 0.0
    
    def reset_to_defaults(self):
        """Reset all settings to default values"""
        for key, value in self.defaults.items():
            self.settings.setValue(key, value)
        self.settings.sync() 