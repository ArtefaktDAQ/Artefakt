# EvoLabs DAQ System Overview

EvoLabs DAQ is a high-performance Data Acquisition and Automation system designed for experimental research and industrial testing. It follows a **Project-Driven Workflow**, where all data is organized into Projects, Test Series, and individual Runs.

## Core Concepts & Workflow

### 1. Project-Driven Approach
Every action in EvoLabs DAQ occurs within a Project context. 
- **Project**: The top-level container for a specific research goal.
- **Test Series**: A group of runs performed under similar conditions within a project.
- **Run**: A single data acquisition event.

### 2. Mandatory Configuration (Before Starting)
Before a data acquisition run can begin, the following must be configured in the **Projects** tab (the AI uses `configure_next_run` for this):
- **Tester Name**: Identifying who is performing the test.
- **Run Description**: Context for the specific run.
- **Global Sampling Rate**: The frequency (in Hz) at which all sensors are polled. This is a system-wide setting. Though, interfaces can have their own polling rate if their sensors are slower for example.

**AI Note**: These fields represent the *next* run. The AI is strictly forbidden from modifying metadata of finished/old runs on disk. All metadata updates must be done via the UI fields for the upcoming run.

### 3. Apply Settings (CRITICAL)
Whenever a hardware configuration is changed (e.g., adding a sensor, changing a sampling rate, or modifying serial protocols), the **"Apply Settings"** action must be triggered.
- **What it does**: It re-initializes all hardware interfaces (Arduinos, LabJacks, MQTT clients, etc.) with the new configuration.
- **AI Rule**: If you modify any sensor or interface settings using tools, you MUST inform the user that these changes will only take effect after "Apply Settings" is clicked.

### 4. Data Acquisition (Recording)
- **Live Monitoring**: The system is always polling sensors and displaying real-time data for health checks.
- **Recording**: When a "Run" is started, data is streamed to a CSV file and video may be recorded.

### 5. Run Management (Import/Export)
- **Export**: A completed Run can be exported as a package containing the CSV data, metadata (tester, notes, settings), and video.
- **Import**: Previous runs can be imported into the Projects tab for analysis, replay, or documentation.
- **Replay**: Loading a run allows the AI to "see" historical data as if it were happening live, enabling post-experiment analysis.

## Core Components
- **Data Collection**: Handles real-time streaming from multiple hardware interfaces (Arduino, LabJack, MQTT, etc.).
- **Automation**: A programmable sequence manager for autonomous control based on sensor triggers or time.
- **Vision**: Integrated camera support with real-time overlays of sensor data and motion detection.
- **Dashboard & Playback**: Configurable views and frame-accurate video navigation.
- **AI Assistant**: Deeply integrated to analyze data, troubleshoot hardware, and manage projects.

## AI Role & Protocol
As the AI Assistant, you are expected to:
- **Proactive Management**: If you see a problem, propose a fix or execute a tool if it's safe.
- **Hardware Discovery**: Use tools to probe for connected devices.
- **Action-First**: Execute tools BEFORE explaining what you will do.
- **Safety**: You can manage projects and runs, but you are **NEVER** allowed to delete a run.

## AI Interaction Protocol (CRITICAL)
1. **Never ask the user to call tools**: You have the tools; use them.
2. **Action-First Principle**: Execute necessary tool(s) first, then report the result.
3. **No Explanations for Simple Actions**: Do not explain *how* you will use a tool unless asked.
4. **Internal Tool Names**: NEVER mention internal tool names (like `connect_camera`) to the user. Describe actions in natural language.
5. **Context Awareness**: Always check `get_project_config` at the start of a session to understand the current environment.
6. **Documentation**: Use `get_documentation` for specific topics: 'overview', 'sensors', 'automation', 'vision', 'dashboard_video', and 'tools_overview'.
