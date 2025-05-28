# Artefakt DAQ

A comprehensive Data Acquisition (DAQ) system built with Python and PyQt6, designed for scientific and industrial data collection applications.

## Features

- **Multi-device Support**: Compatible with Arduino, LabJack U3 and T-series devices (T4, T7) and other serial devices by a configurable interface
- **Real-time Data Visualization**: Live plotting and monitoring capabilities
- **Video Integration**: NDI video streaming and FFmpeg-based video processing
- **Data Export**: Export data in various formats (CSV, JSON, etc.)
- **Modern UI**: Dark-themed interface with intuitive controls
- **Configurable Settings**: Customizable acquisition parameters and device settings
- **Automation Capabilities**: Comprehensive automation framework with time-based triggers (specific times, duration intervals), sensor value thresholds, event-driven sequences, and multi-step programmable control workflows for unattended operation

## Requirements

### System Requirements
- Windows 10/11 (primary support)
- Python 3.8 or higher
- Minimum 4GB RAM
- USB ports for device connections

### Hardware Support
- LabJack U3 devices
- LabJack T-series devices (T4, T7)
- Arduino-compatible microcontrollers
- NDI-compatible video sources

## Installation

You can use Artefakt DAQ in two ways: as a standalone executable or by running from source code.

### Option 1: Standalone Executable (Recommended for End Users)

#### Download and Setup
1. Download the latest `Artefakt_DAQ.exe` from the releases section
2. Create a folder for the application (e.g., `C:\Artefakt_DAQ\`)
3. Place the executable in this folder

#### Option 1: Run Artefakt_DAQ.exe
Double-click `Artefakt_DAQ.exe` to launch

### Option 2: Running from Source Code

#### 1. Clone the Repository
```bash
git clone <repository-url>
cd "EvoLabs DAQ PY"
```

#### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

## Additional Software

#### LabJack Drivers
- Download and install LabJack drivers from [LabJack's official website](https://labjack.com/support/software/installers)
- For T-series devices, install LJM (LabJack Modbus) drivers

#### NDI SDK (Optional)
- For NDI video streaming functionality, download and install the NDI SDK from [NDI's website](https://ndi.video/sdk/)
- This is required only if you plan to use NDI video features

## Usage

### Using the Standalone Executable

#### Basic Operation
1. **Launch**: Double-click `Artefakt_DAQ.exe`
2. **Connect Devices**: Use the device-specific tabs (Arduino, LabJack, Camera) or the automation tab
3. **Start Acquisition**: Click "Start" to begin data collection
4. **Monitor Data**: View real-time data in the Dashboard and Graphs tabs
5. **Describe the Data** Make notes on what happend when the data gets interesting

#### Key Features
- **Dashboard**: Overview of all connected devices and current status
- **Sensors**: Configure and monitor sensor inputs
- **Camera**: Video capture and recording with overlay support
- **Automation**: Set up sequences to automate things
- **Projects**: Organize and manage different experimental setups
- **Settings**: Configure devices, file paths, and application preferences

#### Troubleshooting
- **Application won't start**: Ensure you have administrator privileges if connecting to hardware
- **Device not detected**: Check USB connections and install appropriate drivers
- **Video issues**: Verify camera connections and FFmpeg functionality
- **Data export problems**: Check write permissions in the output directory

### Running from Source Code

#### Development Mode
```bash
python main.py
```

#### Building Your Own Executable
To create a standalone executable from source:
```bash
pyinstaller Artefakt.spec
```

The executable will be created in the `dist/` folder as `Artefakt_DAQ.exe`.

## Project Structure

```
├── app/                    # Main application package
│   ├── core/              # Core functionality
│   ├── ui/                # User interface components
│   ├── controllers/       # Device controllers
│   ├── models/           # Data models
│   ├── utils/            # Utility functions
│   └── settings/         # Configuration management
├── assets/               # Images and icons
├── data/                 # Data storage directory
├── templates/            # Template files
├── Arduino example code/ # Example Arduino sketches
├── main.py              # Application entry point
├── requirements.txt     # Python dependencies
├── Artefakt.spec       # PyInstaller specification
└── ffmpeg.exe          # FFmpeg executable (see licensing below)
```

## Configuration

### For Executable Users
The application automatically creates and manages configuration files in the same directory as the executable:
- `settings.json`: User preferences, device configurations, and application settings
- `config.json`: Core application settings (auto-generated)

All settings can be configured through the application's Settings interface - no manual file editing required.

### For Developers
When running from source, the application uses configuration files in the project directory:
- `config.json`: Core application settings
- `settings.json`: User preferences and device configurations

## Data Storage

### Executable Version
- **Data Files**: Stored in `data/` folder next to the executable
- **Video Recordings**: Stored in `recordings/` folder (configurable in settings)
- **Log Files**: Stored in `logs/` folder for troubleshooting
- **Exports**: Default location is `exports/` folder (configurable)

### Source Code Version
Data is stored in the project directory structure as defined in the Project Structure section.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](#license-text) section below for details.

### Third-Party Software Licensing

#### FFmpeg
This project includes `ffmpeg.exe` for video processing capabilities. FFmpeg is licensed under the LGPL v2.1+ license. The inclusion of the FFmpeg executable does not affect the licensing of this project's source code, but users should be aware of FFmpeg's licensing terms:

- **FFmpeg License**: LGPL v2.1+ (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)
- **FFmpeg Source**: https://ffmpeg.org/
- **Compliance**: The FFmpeg executable is distributed as-is without modifications. Users may replace it with their own FFmpeg build if desired.

For commercial use or redistribution, please review FFmpeg's licensing requirements at: https://ffmpeg.org/legal.html

#### Other Dependencies
All Python dependencies are listed in `requirements.txt` with their respective licenses. Most are permissively licensed (MIT, BSD, Apache 2.0).

## License Text

GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) 2025 evo-labs.io

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For the full license text, visit: https://www.gnu.org/licenses/gpl-3.0.html

