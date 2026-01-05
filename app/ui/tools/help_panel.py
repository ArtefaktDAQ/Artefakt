"""
Help Panel Component

Provides context-sensitive help for tools.
Collapsible panels with explanations for beginners.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QFrame, QTextEdit,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class HelpSection(QFrame):
    """A collapsible help section"""
    
    def __init__(self, title: str, content: str, icon: str = "📖", parent=None):
        super().__init__(parent)
        self.title = title
        self.content = content
        self.icon = icon
        self.is_expanded = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #252540;
                border: 1px solid #3a3a5c;
                border-radius: 6px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header (clickable)
        self.header = QPushButton(f"▶ {self.icon} {self.title}")
        self.header.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #A0A0D0;
                border: none;
                padding: 8px 12px;
                text-align: left;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2d2d50;
                color: #fff;
            }
        """)
        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header)
        
        # Content (hidden by default)
        self.content_widget = QLabel(self.content)
        self.content_widget.setWordWrap(True)
        self.content_widget.setStyleSheet("""
            QLabel {
                color: #B0B0C0;
                padding: 10px 15px;
                font-size: 11px;
                line-height: 1.5;
                background-color: #1e1e35;
                border-top: 1px solid #3a3a5c;
            }
        """)
        self.content_widget.setVisible(False)
        layout.addWidget(self.content_widget)
    
    def _toggle(self):
        self.is_expanded = not self.is_expanded
        self.content_widget.setVisible(self.is_expanded)
        
        if self.is_expanded:
            self.header.setText(f"▼ {self.icon} {self.title}")
        else:
            self.header.setText(f"▶ {self.icon} {self.title}")
    
    def expand(self):
        if not self.is_expanded:
            self._toggle()
    
    def collapse(self):
        if self.is_expanded:
            self._toggle()


class HelpPanel(QFrame):
    """Main help panel with multiple sections"""
    
    # Signal to hide help panel
    close_requested = pyqtSignal()
    
    def __init__(self, title: str = "Help", parent=None):
        super().__init__(parent)
        self.title = title
        self.sections = []
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame#HelpPanel {
                background-color: #1a1a30;
                border-left: 2px solid #4a4a80;
                border-radius: 0px;
            }
        """)
        self.setObjectName("HelpPanel")
        self.setMinimumWidth(300)
        self.setMaximumWidth(400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d6c, stop:1 #2a2a4a);
                border: none;
                padding: 10px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 8, 8)
        
        help_icon = QLabel("❓")
        help_icon.setFont(QFont("Segoe UI Emoji", 16))
        help_icon.setStyleSheet("background: transparent;")
        header_layout.addWidget(help_icon)
        
        title_label = QLabel(self.title)
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #fff; background: transparent;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: none;
                font-size: 14px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                color: #F44336;
            }
        """)
        close_btn.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(close_btn)
        
        layout.addWidget(header_frame)
        
        # Scroll area for sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #1a1a30;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #4a4a6c;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #5a5a8c;
            }
        """)
        
        self.sections_widget = QWidget()
        self.sections_widget.setStyleSheet("background-color: transparent;")
        self.sections_layout = QVBoxLayout(self.sections_widget)
        self.sections_layout.setContentsMargins(8, 8, 8, 8)
        self.sections_layout.setSpacing(6)
        self.sections_layout.addStretch()
        
        scroll.setWidget(self.sections_widget)
        layout.addWidget(scroll)
    
    def add_section(self, title: str, content: str, icon: str = "📖"):
        """Add a help section"""
        section = HelpSection(title, content, icon)
        self.sections.append(section)
        # Insert before the stretch
        self.sections_layout.insertWidget(self.sections_layout.count() - 1, section)
        return section
    
    def clear_sections(self):
        """Remove all sections"""
        for section in self.sections:
            section.setParent(None)
            section.deleteLater()
        self.sections.clear()
    
    def expand_all(self):
        """Expand all sections"""
        for section in self.sections:
            section.expand()
    
    def collapse_all(self):
        """Collapse all sections"""
        for section in self.sections:
            section.collapse()


# ============================================================================
# HELP CONTENT FOR EACH TOOL
# ============================================================================

CALIBRATION_HELP = {
    "title": "Sensor Calibration Guide",
    "sections": [
        {
            "title": "What is Calibration?",
            "icon": "🎯",
            "content": """Calibration is the process of adjusting a sensor's readings to match known, accurate reference values.

Over time, sensors can drift or be affected by environmental factors, leading to inaccurate measurements. Calibration corrects this by:
• Comparing sensor readings against known standards
• Calculating correction factors (offset and gain)
• Applying these factors to future readings

Think of it like setting your bathroom scale: if it shows 2 lbs when empty, you need a -2 lb offset to get accurate weight readings."""
        },
        {
            "title": "Step-by-Step Guide",
            "icon": "📋",
            "content": """1️⃣ SELECT SENSOR
Choose the sensor you want to calibrate from the dropdown. The current reading will be displayed.

2️⃣ CHOOSE METHOD
• Linear: Best for most sensors. Uses y = mx + b equation. Need at least 2 points.
• Polynomial: For non-linear sensors. Need 3+ points.
• Manual Offset/Gain: Enter known values directly.

3️⃣ ADD CALIBRATION POINTS
Apply known references to your sensor:
• "Measured" = what the sensor shows
• "Actual" = the true/reference value

Examples:
• Temperature: Use ice water (0°C) and boiling water (100°C)
• Pressure: Use a calibrated reference gauge
• Load cell: Use certified weights

4️⃣ CALCULATE & APPLY
Click "Calculate" to compute the correction. Check the R² value (closer to 1.0 = better fit). Apply to the sensor when satisfied."""
        },
        {
            "title": "Understanding R² (Fit Quality)",
            "icon": "📊",
            "content": """R² (R-squared) tells you how well the calibration fits your data:

🟢 R² > 0.99: Excellent fit - very accurate calibration
🟡 R² > 0.95: Good fit - acceptable for most applications
🟠 R² > 0.90: Moderate fit - consider adding more points
🔴 R² < 0.90: Poor fit - check for errors or outliers

If your R² is low:
• Verify your reference values are accurate
• Check for measurement errors
• Make sure conditions are stable during calibration
• Try using more calibration points"""
        },
        {
            "title": "Calibration Methods Explained",
            "icon": "🔬",
            "content": """LINEAR CALIBRATION (y = mx + b)
• m = gain (slope) - how much to scale the reading
• b = offset - constant to add/subtract
• Best for: thermocouples, strain gauges, most voltage sensors

POLYNOMIAL CALIBRATION
• For sensors with curved response
• y = ax² + bx + c (or higher orders)
• Best for: NTC thermistors, some pressure sensors

MANUAL OFFSET + GAIN
• Enter values directly if you know them
• Useful when applying factory calibration data
• Formula: calibrated = (raw × gain) + offset

TIP: Start with Linear. Only use Polynomial if you see curvature in the calibration plot."""
        },
        {
            "title": "Calibration Tips",
            "icon": "💡",
            "content": """✓ Use at least 2 points for linear, 3+ for polynomial
✓ Space your calibration points across the measurement range
✓ Wait for readings to stabilize before capturing
✓ Use certified/traceable reference standards when possible
✓ Recalibrate periodically (monthly or before important tests)
✓ Document your calibration for traceability

COMMON MISTAKES:
✗ Only using one calibration point
✗ Not letting the sensor stabilize
✗ Using the same point for min and max
✗ Ignoring environmental conditions (temperature affects many sensors)"""
        }
    ]
}

FFT_HELP = {
    "title": "FFT Spectrum Analyzer Guide",
    "sections": [
        {
            "title": "What is FFT Analysis?",
            "icon": "📊",
            "content": """FFT (Fast Fourier Transform) converts a signal from the time domain to the frequency domain.

In simple terms: Instead of seeing how a signal changes over time, you see what frequencies make up that signal.

USE CASES:
• Finding vibration frequencies in machinery
• Detecting electrical noise (50/60 Hz hum)
• Analyzing audio signals
• Identifying resonances and harmonics
• Diagnosing motor/bearing problems

Example: A vibrating motor might show its rotation frequency (e.g., 60 Hz) and harmonics (120 Hz, 180 Hz...)"""
        },
        {
            "title": "Understanding the Settings",
            "icon": "⚙️",
            "content": """FFT SIZE (128 to 8192)
• Larger = better frequency resolution, but slower
• Smaller = faster updates, but coarser resolution
• Recommended: 1024 or 2048 for most uses

WINDOW TYPE
• Hanning: Best all-around choice ⭐
• Hamming: Good for closely-spaced frequencies
• Blackman: Best for weak signals near strong ones
• Rectangular: No windowing (avoid unless you know why)
• Kaiser: Adjustable trade-off (advanced use)

dB SCALE
• ON: Logarithmic scale (shows weak and strong signals together)
• OFF: Linear scale (emphasizes strong signals)
• Recommend: Keep ON for most analysis

LOG FREQUENCY
• ON: Logarithmic frequency axis (good for audio)
• OFF: Linear frequency axis (better for vibration)"""
        },
        {
            "title": "Reading the Spectrum",
            "icon": "📈",
            "content": """X-AXIS: Frequency (Hz)
Shows what frequencies are present in your signal.

Y-AXIS: Amplitude (dB or linear)
Shows how strong each frequency component is.
• dB: 0 dB = reference, negative = weaker
• Linear: Actual amplitude values

PEAKS
• Tall peaks indicate dominant frequencies
• The fundamental is usually the tallest
• Harmonics appear at 2x, 3x, 4x... the fundamental

NOISE FLOOR
• The flat baseline level
• Signals should be well above this
• High noise floor = noisy measurement"""
        },
        {
            "title": "THD (Total Harmonic Distortion)",
            "icon": "🎵",
            "content": """THD measures how much harmonic content is in your signal compared to the fundamental.

THD < 1%: Excellent, very clean signal ✅
THD 1-5%: Good for most applications ✅
THD 5-10%: Moderate distortion ⚠️
THD > 10%: Significant distortion ❌

HIGH THD CAUSES:
• Clipping (signal too strong)
• Non-linear components
• Electromagnetic interference
• Mechanical imbalances (in vibration)

LOW THD DESIRED FOR:
• Audio signals
• Clean power measurements
• Precision sensors"""
        },
        {
            "title": "The Spectrogram (Waterfall)",
            "icon": "🌊",
            "content": """The spectrogram shows how frequencies change over time.

HOW TO READ IT:
• X-axis: Time (older on left, newer on right)
• Y-axis: Frequency (low at bottom, high at top)
• Color: Signal strength (brighter = stronger)

USE CASES:
• Seeing transient events
• Monitoring machinery startup/shutdown
• Tracking drifting frequencies
• Visualizing speech or music

Tips:
• Click "Clear" to start fresh
• Brighter colors = stronger signals
• Horizontal lines = steady frequencies
• Vertical lines = impulse events

Spectrogram controls:
• dB range: Set min/max dB for the color scale (e.g., -60..0). Narrow the window for more contrast on speech.
• Auto-scale dB (frame): Use the 5th/95th percentile of each frame to adapt contrast automatically.
• Normalize per frame: Re-center each frame so its loudest bin is 0 dB. Helps speech/music show contrast even when the input is loud.
• If the plot looks like a solid block, lower input gain, narrow the dB range, or enable auto-scale/normalization."""
        },
        {
            "title": "Microphone Input",
            "icon": "🎤",
            "content": """This tool can analyze live audio from your microphone.

TO USE:
1. Select a microphone from the sensor dropdown
2. Click "Start Live" for continuous analysis
3. Speak, play music, or analyze ambient noise

APPLICATIONS:
• Test speaker response
• Measure room acoustics
• Identify noise sources
• Audio equipment testing

RPM ESTIMATES:
• Enter pulses/blades per revolution in the Pulses/Rev field
• Fundamental frequency × 60 / pulses gives estimated RPM

NOTE: Sample rate is 44.1 kHz, allowing analysis up to ~22 kHz (Nyquist frequency)."""
        }
    ]
}

STATISTICS_HELP = {
    "title": "Statistics Dashboard Guide",
    "sections": [
        {
            "title": "What Are These Statistics?",
            "icon": "📊",
            "content": """This dashboard calculates real-time statistics for your sensor data.

MIN / MAX
• Minimum and maximum values recorded
• Useful for finding peaks and limits

MEAN (Average)
• Sum of all values ÷ number of values
• Shows the central tendency

MEDIAN
• The middle value when sorted
• Less affected by outliers than mean

STANDARD DEVIATION (Std Dev)
• How spread out the values are
• Low = consistent readings
• High = noisy or varying signal

TREND
• Shows if values are increasing/decreasing
• Calculated using linear regression slope"""
        },
        {
            "title": "Understanding the Histogram",
            "icon": "📊",
            "content": """A histogram shows the distribution of your data.

HOW TO READ IT:
• X-axis: Value ranges (bins)
• Y-axis: How many samples in each range
• Tall bar = many values in that range

COMMON PATTERNS:

Normal (Bell Curve) 🔔
• Symmetrical around the mean
• Most values near the center
• Expected for many physical measurements

Skewed ↗️ or ↙️
• Peak shifted left or right
• May indicate a limit or bias

Bimodal (Two Peaks) 🏔️🏔️
• Two distinct value ranges
• May indicate two different states

BINS SETTING:
• More bins = finer detail
• Fewer bins = smoother shape
• 20-40 bins usually works well"""
        },
        {
            "title": "Distribution Statistics",
            "icon": "📐",
            "content": """RANGE
• Difference between max and min
• Shows total spread of data

IQR (Interquartile Range)
• Range of the middle 50% of data
• Q3 - Q1
• Less sensitive to outliers than Range

Q1 (25th Percentile)
• 25% of values are below this

Q3 (75th Percentile)
• 75% of values are below this

COEFFICIENT OF VARIATION (CV)
• Standard deviation ÷ mean × 100%
• Allows comparing variability between different sensors
• Lower = more consistent

SKEWNESS
• 0 = symmetric
• Positive = tail to the right
• Negative = tail to the left

KURTOSIS
• How "peaked" or "flat" the distribution is
• 0 = normal distribution
• Positive = more peaked
• Negative = flatter"""
        },
        {
            "title": "Tips for Analysis",
            "icon": "💡",
            "content": """✓ Look for stability: Low std dev means consistent sensor

✓ Check for outliers: Compare mean vs median - if very different, you may have outliers

✓ Monitor trends: A stable process should show "→ Stable" trend

✓ Use histogram to find issues:
  • Multiple peaks may indicate switching states
  • Long tails may indicate occasional spikes

✓ Compare sensors: Use CV to compare consistency between different sensors with different scales

✓ Let it run: More samples = more reliable statistics"""
        }
    ]
}

DIAGNOSTICS_HELP = {
    "title": "Hardware Diagnostics Guide",
    "sections": [
        {
            "title": "Interface Status Cards",
            "icon": "📟",
            "content": """Each card shows the connection status of an interface type:

ARDUINO
• Shows COM port and baud rate
• Lists number of active sensors
• Green indicator = connected

LABJACK
• Shows model (T7, etc.) and serial
• Lists active channels
• Data rate in samples/second

CAMERA
• Shows camera name and resolution
• Current FPS (frames per second)
• Backend in use

Click "Test Connection" on any card to verify the interface is responding and see current readings."""
        },
        {
            "title": "Serial Ports Table",
            "icon": "🔌",
            "content": """Shows all detected serial ports on your computer.

PORT
• The device name (COM3, /dev/ttyUSB0, etc.)

DESCRIPTION
• Hardware description from the driver
• Helps identify what's connected

VID:PID
• Vendor ID and Product ID
• Unique to each device type
• Common ones:
  • Arduino Uno: 2341:0043
  • Arduino Mega: 2341:0042

STATUS
• "Available" = can be used
• "In Use" = currently open by this app

Click "Scan Ports" to refresh the list after connecting/disconnecting devices."""
        },
        {
            "title": "Data Rate Graph",
            "icon": "📈",
            "content": """Shows how many data samples are received per second over time.

CURRENT RATE
• Samples received in the last second
• Should match your expected sample rate

PEAK
• Highest rate recorded
• May spike during bursts

AVERAGE
• Mean rate over the monitoring period
• Most reliable indicator

TROUBLESHOOTING:
• Rate = 0: No data received (check connections)
• Low rate: Baud rate issue or slow sensor
• Erratic rate: Communication problems
• Dropping rate: Buffer overflow or disconnection"""
        },
        {
            "title": "Serial Monitor",
            "icon": "📟",
            "content": """A console for viewing and sending serial data.

COLORS:
• Green ← : Data received
• Yellow → : Data sent
• Blue ℹ : Info messages
• Red ✖ : Errors

USING THE MONITOR:
1. Type a command in the input field
2. Press Enter or click "Send"
3. Response appears in the console

COMMON USES:
• Debug Arduino communication
• Send manual commands
• Monitor raw sensor data
• Check for errors

TIP: Enable "Auto-scroll" to always see the latest messages."""
        },
        {
            "title": "Troubleshooting Tips",
            "icon": "🔧",
            "content": """DEVICE NOT DETECTED:
• Check USB cable (try another)
• Install/update drivers
• Try a different USB port
• Restart the application

NO DATA RECEIVED:
• Verify baud rate matches device
• Check Arduino code is running
• Look for serial monitor conflicts
• Check for wiring issues

ERRATIC READINGS:
• Check for loose connections
• Shield cables from interference
• Verify power supply is stable
• Check for grounding issues

SLOW DATA RATE:
• Reduce sensor count
• Increase baud rate
• Simplify Arduino code
• Check for blocking operations"""
        }
    ]
}

CALCULATOR_HELP = {
    "title": "Engineering Calculator Guide",
    "sections": [
        {
            "title": "Unit Converter",
            "icon": "🔄",
            "content": """Convert between common engineering units.

CATEGORIES:
• Temperature: °C, °F, Kelvin
• Pressure: Pa, bar, psi, atm, mmHg...
• Length: m, mm, in, ft, mi...
• Mass: kg, g, lb, oz...
• Frequency: Hz, kHz, MHz, rpm...
• Electrical: V, mV, A, mA, Ω, kΩ...

HOW TO USE:
1. Select a category
2. Enter the value to convert
3. Choose "From" and "To" units
4. Result updates automatically

The reference table shows the value in all available units at once."""
        },
        {
            "title": "RTD / NTC Calculator",
            "icon": "🌡️",
            "content": """Calculate temperature from resistance (or vice versa) for temperature sensors.

SUPPORTED SENSORS:
• PT100: 100Ω at 0°C (most common industrial RTD)
• PT1000: 1000Ω at 0°C (better for long cables)
• NTC 10kΩ: 10kΩ at 25°C (common thermistor)
• NTC 100kΩ: 100kΩ at 25°C (high-temp thermistor)

USAGE:
Temperature → Resistance:
• You know the temperature
• Calculates expected resistance

Resistance → Temperature:
• You measured resistance
• Calculates the temperature

FORMULAS USED:
• RTD: Callendar-Van Dusen equation
• NTC: Steinhart-Hart approximation

REFERENCE TABLE:
Shows common temperature/resistance pairs for the selected sensor type."""
        },
        {
            "title": "Electrical Calculators",
            "icon": "⚡",
            "content": """OHM'S LAW (V = I × R)
• Voltage (V): Electrical potential
• Current (I): Flow of electrons (Amps)
• Resistance (R): Opposition to flow (Ohms)
• Power: Automatically calculated (P = V × I)

Enter any two values, click "Calculate" on the third.

dB CALCULATOR
Decibels express ratios logarithmically.

Ratio → dB:
• Power dB = 10 × log₁₀(ratio)
• Voltage dB = 20 × log₁₀(ratio)

dB → Ratio:
• Converts back to linear ratio

Common values:
• +3 dB ≈ 2× power / 1.41× voltage
• +6 dB ≈ 4× power / 2× voltage
• +10 dB = 10× power / 3.16× voltage

FREQUENCY ↔ PERIOD
• Frequency = 1 / Period
• Enter frequency, get period (or vice versa)
• Handles all SI prefixes (ms, μs, ns, kHz, MHz...)"""
        },
        {
            "title": "Signal Scaling",
            "icon": "📊",
            "content": """Calculate the formula to convert raw sensor signals to engineering units.

EXAMPLE:
A pressure sensor outputs:
• 0-5V for 0-100 bar

Enter:
• Input Min: 0, Max: 5 (V)
• Output Min: 0, Max: 100 (bar)

Result:
• Slope (m): 20
• Offset (b): 0
• Formula: bar = 20 × V + 0

USAGE:
Enter the input range (what sensor outputs) and output range (what you want to display).

The calculator gives you:
• Slope (m): Multiplication factor
• Offset (b): Value to add
• Formula: For reference

TEST CONVERSION:
Enter any input value to verify the scaling works correctly."""
        }
    ]
}

OPTICAL_SENSOR_HELP = {
    "title": "Optical Sensor Configuration Guide",
    "sections": [
        {
            "title": "What are Optical Sensors?",
            "icon": "📹",
            "content": """Optical sensors use cameras to detect and measure visual phenomena:

DETECTION MODES:
• 💡 Light Events: Detect bright flashes (scintillation, particle impacts)
• ☀️ Brightness: Measure overall light levels and changes
• 🎨 Color Tracking: Monitor color values and presence
• 📍 Position Tracking: Follow movement of bright/colored objects
• ✨ Particle Counter: Count distinct bright spots or particles
• 📊 Fill Level: Measure liquid levels in containers

COMMON USES:
• Detecting cosmic rays or radiation events
• Monitoring chemical reactions (color changes)
• Tracking particle movement in fluids
• Measuring liquid levels in experiments
• Quality control and automated inspection"""
        },
        {
            "title": "Threshold Modes Explained",
            "icon": "📊",
            "content": """ABSOLUTE THRESHOLD (1-255):
A fixed brightness value. Pixels above this value are detected.
• 30 = detect moderately bright spots
• 50 = detect only bright spots
• 100 = detect only very bright spots
Use when lighting conditions are stable.

RELATIVE THRESHOLD (σ / Sigma):
Uses statistical analysis of the image noise.
σ (sigma) = Standard Deviation of pixel values.

What is σ (Sigma)?
Standard deviation measures how spread out the pixel values are. In a dark camera image, most pixels are similar (low σ). A bright spot stands out by many σ above the average.

3σ THRESHOLD (Recommended):
• Detects pixels >3 standard deviations above baseline
• Statistically: Only 0.3% chance of false positive
• Self-adjusting to lighting changes
• Best for detecting real events vs noise

When to use which:
• 2σ: More sensitive, may include noise
• 3σ: Good balance (recommended for most uses)
• 4σ: Very strict, only obvious events
• 5σ: Extremely strict, scientific standard"""
        },
        {
            "title": "Particle Counter Mode",
            "icon": "✨",
            "content": """PARTICLE COUNTER counts distinct bright objects in each frame.

HOW IT WORKS:
1. Applies brightness threshold to find bright pixels
2. Groups connected bright pixels into "contours"
3. Filters by size (min/max pixels)
4. Counts valid contours as particles

SETTINGS:
• Brightness Threshold: Minimum brightness to detect
• Min Pixels: Smallest particle size (filters noise)
• Max Pixels: Largest particle size (filters large objects)
• Cooldown: Time between counts to avoid double-counting

OUTPUT VALUES:
• particle_count: Number of particles in current frame
• total_particles: Running total since start
• avg_particle_size: Average size in pixels

APPLICATIONS:
• Bubble counting in liquids
• Dust/particle detection
• Cell counting in microscopy
• Debris tracking in chambers
• Scintillation event counting

TIPS:
• Use dark background for best contrast
• Adjust min/max pixels to filter unwanted detections
• Test with Preview to verify settings"""
        },
        {
            "title": "Camera Settings",
            "icon": "🎥",
            "content": """CAMERA SELECTION:
• Camera ID: Which camera to use (0 = default)
• Test different IDs if multiple cameras connected

RESOLUTION:
• Higher = more detail, but slower processing
• 640x480: Good balance for most experiments
• 320x240: Fastest, for simple detection
• 1280x720: High detail, slower updates

SAMPLE RATE:
• How often to capture and analyze frames
• 10 Hz: Good for most slow-changing phenomena
• 30 Hz: For faster events (particle tracking)
• Higher rates need faster computers"""
        },
        {
            "title": "Event Saving & Output",
            "icon": "💾",
            "content": """EVENT IMAGES:
• Save snapshots when events are detected
• Useful for verifying detections and analysis
• Output Directory: Where to save event images
• Files named with timestamp and sensor data

DATA OUTPUT:
• Sensor values appear in graphs and CSV logs
• Light Events: Number of events detected
• Brightness: Mean brightness value
• Color: Hue/saturation values
• Position: X,Y coordinates of tracked object
• Particle Count: Number of detected particles

TROUBLESHOOTING:
• No events detected: Lower threshold or check lighting
• Too many false events: Raise threshold or adjust filters
• Poor tracking: Check camera focus and lighting conditions
• Missing particles: Increase max pixel size or lower threshold"""
        }
    ]
}

AUDIO_SENSOR_HELP = {
    "title": "Audio Sensor Configuration Guide",
    "sections": [
        {
            "title": "What are Audio Sensors?",
            "icon": "🎤",
            "content": """Audio sensors use microphones to capture and analyze sound:

MEASUREMENT MODES:
• 📊 RMS Level: Average signal power (perceived loudness)
• 📈 Peak Amplitude: Maximum signal level in each window
• 🎵 Dominant Frequency: Most prominent frequency via FFT
• 🎚️ Band Energy: Energy in specific frequency ranges
• 〰️ Zero Crossing Rate: How often signal crosses zero (pitch indicator)
• 🔊 dB Level: Signal level in decibels

COMMON USES:
• Monitoring reaction sounds (bubbling, cracking)
• Detecting mechanical vibrations
• Audio quality analysis
• Environmental noise monitoring
• Process control (machinery sounds)"""
        },
        {
            "title": "Interface & Basic Settings",
            "icon": "⚙️",
            "content": """AUDIO DEVICE SELECTION:
• Choose your microphone or audio input
• Default: System default audio device
• Refresh button: Update device list if needed

SAMPLE RATE & BUFFERING:
• Managed automatically for stability
• Defaults to 44100 Hz with 2048-sample chunks
• No manual adjustment needed in the dialog

OUTPUT RATE:
• How often sensor values are sent (Hz)
• 10 Hz: Standard, smooth graphs
• Higher: More responsive, more data"""
        },
        {
            "title": "Measurement Modes Explained",
            "icon": "📊",
            "content": """RMS LEVEL (Root Mean Square):
• Represents perceived loudness
• Calculated as √(mean of squared values)
• Range: 0.0 (silence) to 1.0 (full scale)
• Good for overall sound intensity monitoring

PEAK AMPLITUDE:
• Maximum signal level in each window
• Shows brief loud sounds or transients
• Useful for detecting sudden events
• Range: 0.0 to 1.0

dB LEVEL (Decibels):
• Scale: dBFS (digital full scale), not SPL-calibrated
• 0 dBFS = maximum digital level
• Negative values = quieter sounds
• -60 dBFS = very quiet, -20 dBFS = moderate

DOMINANT FREQUENCY:
• Most prominent frequency via FFT
• Output in Hz (cycles per second)
• Human hearing: 20 Hz - 20,000 Hz
• Speech: typically 100-300 Hz fundamental

BAND ENERGY:
• Energy in a specific frequency range
• Set your own Low/High cutoff frequencies
• Example: 200-400 Hz for male voice
• Useful for focusing on specific sounds

ZERO CROSSING RATE:
• How often signal crosses zero
• Noisy sounds = high crossing rate
• Pure tones = low crossing rate
• Units: crossings per second"""
        },
        {
            "title": "Processing Settings",
            "icon": "🔧",
            "content": """SMOOTHING (0-99%):
• Higher = smoother but slower response
• 0% = raw values, may jump around
• 30% = recommended for most uses
• 80%+ = very smooth, slow to react

NOISE GATE:
• Ignores signals below this level
• Filters out background noise
• 0.01 = catches most sounds
• 0.1 = only moderate/loud sounds
• Higher = more noise rejection

PEAK HOLD (ms):
• How long to remember the peak level
• 500 ms = half second memory
• Shows maximum reached recently
• Useful for transient detection

FREQUENCY BAND (for Band Energy):
• Low Frequency: Start of range (Hz)
• High Frequency: End of range (Hz)
• Common ranges:
  - Bass: 20-200 Hz
  - Speech: 200-4000 Hz
  - High frequencies: 4000-20000 Hz"""
        },
        {
            "title": "Level Meter & Monitoring",
            "icon": "📈",
            "content": """REAL-TIME LEVEL METER:
• Shows current audio levels visually
• Green: Normal levels (0-60%)
• Yellow: Moderate levels (60-85%)
• Red: High levels (>85%, potential clipping)

PEAK HOLD MARKER:
• White vertical line shows peak
• Shows maximum level since reset
• Helps identify brief loud events

CLIPPING WARNING:
• Red meter = signal too high
• Clipping distorts measurements
• Solutions:
  - Move microphone further away
  - Reduce system input volume
  - Use attenuated input

LIVE PREVIEW:
• Start Preview to test settings
• Value display shows current reading
• Adjust settings and see immediate effect
• Stop preview before closing dialog

TROUBLESHOOTING:
• No audio: Check device selection
• Always maxed: Reduce input gain
• Too quiet: Get closer to sound source
• Erratic values: Increase smoothing"""
        }
    ]
}


SENSORS_HELP = {
    "title": "Sensors Guide",
    "sections": [
        {
            "title": "Getting Started",
            "icon": "🚀",
            "content": """SENSORS TAB OVERVIEW:
This tab lets you configure and manage all your data acquisition sensors.

INTERFACE CARDS (TOP):
Click on any interface card to open its configuration:
• Arduino - USB serial sensors
• LabJack - High-precision DAQ
• Read CSV - External CSV file monitoring
• Optical Sensor - Camera-based measurements
• Audio Sensor - Microphone input
• MQTT - IoT and network sensors
• Remote DAQ - Distributed gRPC streaming
• Serial Sensors - Custom serial devices

SENSOR TABLE (BELOW):
Shows all configured sensors with their current values and settings."""
        },
        {
            "title": "Adding Sensors",
            "icon": "➕",
            "content": """TO ADD A NEW SENSOR:

1️⃣ CLICK INTERFACE CARD
Click the appropriate interface card (Arduino, LabJack, CSV, etc.) to open its settings.

2️⃣ CONFIGURE CONNECTION
Set up the connection parameters (COM port, baud rate, file path, etc.).

3️⃣ ADD SENSOR
Click "Add Sensor" or "Add Mapping" button and configure:
• Name: Descriptive sensor name
• Interface: Which interface it connects to
• Channel/Index/Column: Which input to read
• Unit: Measurement unit (°C, Pa, etc.)

4️⃣ ENABLE GRAPH
Check "Show in Graph" to display the sensor in visualizations."""
        },
        {
            "title": "Sensor Table Columns",
            "icon": "📊",
            "content": """GRAPH CHECKBOX:
☑️ Check to show sensor in graph view
(Data is always recorded regardless)

SENSOR NAME:
The display name for your sensor

VALUE:
Current reading with units

INTERFACE:
Which interface the sensor is connected to

OFFSET/UNIT:
Calibration offset and measurement unit

STALE xINT:
Gap threshold multiplier (factor / sampling rate). If no data is received within this time, the value is marked as stale.

How it works:
• The timeout = factor / sampling rate
• Example: If factor is 5.0 and sampling is 10Hz, timeout = 0.5s
• When stale, the value shows as grayed out and graphs show gaps
• Leave empty to use the global default (typically 5.0)
• Lower values = more sensitive to missing data
• Higher values = more tolerant of occasional delays

SMOOTH (Smoothing):
Checkbox to enable moving average filtering for this sensor (last 10 values).

Benefits:
• Reduces noise in readings
• Smoother graph lines
• Better for noisy sensors or electrical interference

When to use:
• Enable for sensors with electrical noise
• Useful for analog sensors on long cables
• Helps with vibration or mechanical noise
• Disable if you need immediate, unfiltered readings

Note: Smoothing applies a rolling average over the last 10 values. The checkbox is per-sensor, so you can smooth some sensors while keeping others raw.

IMPORTANT - Interface-Specific Behavior:
• LABJACK: Can be configured with a higher internal sampling rate in device settings. When enabled, smoothing uses samples from this higher-rate collection, providing immediate, responsive data with noise reduction. The smoothing window uses the last 10 samples regardless of sampling rate.
• ARDUINO: Runs at the global sampling rate (no higher internal rate). Smoothing will use a rolling average of the last 10 values, which may introduce some delay depending on sampling rate. For immediate readings, disable smoothing on Arduino sensors.

COLOR:
Graph line color for this sensor

CAL. (CALIBRATE):
Click to open calibration wizard"""
        },
        {
            "title": "Interface Types",
            "icon": "🔌",
            "content": """ARDUINO:
• USB serial connection
• Multiple analog/digital channels
• Supports I2C slave devices
• Flexible custom firmware

LABJACK:
• Professional DAQ hardware
• High precision measurements
• Multiple analog inputs
• Digital I/O support

READ CSV:
• Monitor external data files in real-time
• Reads the newest values automatically
• Supports column mapping and regex extraction
• Use for devices that log to local files

Example Regex:
• ([-+]?[0-9.]+) : Extracts numbers like "-12.5"
• ([-+]?\\d*\\.\\d+|\\d+) : More robust number extraction
• Value:\\s*([-+]?[0-9.]+) : Matches "Value: 25.4" and extracts 25.4

OPTICAL SENSOR:
• Camera-based measurement
• Motion/position tracking
• Frame analysis
• Video recording

AUDIO SENSOR:
• Microphone input
• Sound level monitoring
• Frequency analysis
• dB measurements

MQTT:
• IoT and Network protocols
• Subscribe to topics as sensors
• Supports JSON and numeric data
• Real-time remote monitoring

REMOTE DAQ:
• Stream data between Artefakt instances
• gRPC protocol over LAN/VPN
• Remote video and sensor feeds

SERIAL SENSORS:
• Custom serial protocols
• Define send/receive sequences
• Parse custom data formats
• Multiple variables per device"""
        },
        {
            "title": "Calibration",
            "icon": "🎯",
            "content": """WHY CALIBRATE?
Sensors may drift over time or have manufacturing variations. Calibration ensures accurate readings.

HOW TO CALIBRATE:
1. Click the "Cal." button for a sensor
2. Apply known reference values
3. Record measured vs actual values
4. Calculate correction factors

CALIBRATION TYPES:
• Linear: Offset + gain correction
• Polynomial: For non-linear sensors
• Manual: Enter known factors

TIP: Use the Tools > Calibration for advanced options."""
        },
        {
            "title": "Tips & Troubleshooting",
            "icon": "💡",
            "content": """CONNECTION ISSUES:
• Check cable connections
• Verify correct COM port
• Try different baud rates
• Restart the device

NO DATA:
• Ensure sensor is enabled
• Check interface connection
• Verify channel/index settings
• Look for error messages

NOISY READINGS:
• Use calibration offset
• Check electrical connections
• Add filtering in Arduino code
• Shield cables from interference

PERFORMANCE:
• Limit active sensors if needed
• Adjust poll intervals
• Use appropriate data rates"""
        }
    ]
}


AUTOMATION_HELP = {
    "title": "Automation Guide",
    "sections": [
        {
            "title": "What is Automation?",
            "icon": "🤖",
            "content": """Automation lets you create sequences that perform actions automatically based on triggers.

KEY CONCEPTS:
• Sequences: Named collections of automated steps
• Triggers: Conditions that start an action
• Actions: What happens when triggered

EXAMPLE USE CASES:
• Start recording when temperature exceeds threshold
• Take snapshots at regular intervals
• Send commands to Arduino when sensor changes
• Play alerts when conditions are met"""
        },
        {
            "title": "Creating Sequences",
            "icon": "📝",
            "content": """STEP-BY-STEP:

1️⃣ CLICK "NEW SEQUENCE"
Create a new automation sequence with a descriptive name.

2️⃣ ADD STEPS
Each step has a trigger condition and one or more actions.

3️⃣ CONFIGURE TRIGGERS
Set when the step should activate:
• Time-based: After delay or at specific time
• Sensor-based: When value crosses threshold
• Event-based: On button press, recording start/stop

4️⃣ CONFIGURE ACTIONS
Define what happens when triggered:
• Interface commands
• Camera operations
• System notifications

5️⃣ SAVE & TEST
Save your sequence and test it before use."""
        },
        {
            "title": "Types of Triggers",
            "icon": "⚡",
            "content": """TIME-BASED TRIGGERS:
• Delay: Trigger after X seconds/minutes
• Schedule: At specific time of day
• Duration: After recording runs for X time

SENSOR-BASED TRIGGERS:
• Threshold: When value crosses a limit
• Hysteresis: Prevents rapid 'flickering' near the threshold. The trigger stays active until the value moves back past (Threshold +/- Hysteresis).

ADVANCED TRIGGERS:
• Compound: Combine multiple triggers using AND (all must be true) or OR (any must be true) logic.
• Event-based: On recording start/stop or camera events."""
        },
        {
            "title": "Branching & Flow Control",
            "icon": "🔀",
            "content": """Automations are no longer just simple lists! You can now create complex logic:

JUMP TO STEP:
Redirect the sequence to any other step. Useful for creating loops or skipping sections.

CONDITION (IF/ELSE):
Evaluate an expression (e.g., {temp} > 100) and jump to different steps depending on whether it's True or False.

Example:
Step 5: If {pressure} > 200 jump to Step 10 (Alert) else Continue."""
        },
        {
            "title": "Variables & Expressions",
            "icon": "🧮",
            "content": """Variables allow sequences to store data and perform math.

SETTING VARIABLES:
Use the 'Set Variable' action to store a value. You can use math: {count} + 1.

SUBSTITUTIONS:
Use curly braces {} to use sensor values or variables in commands or conditions:
• "TEMP_{ambient_temp}" (String)
• {v1} * 2.5 + {offset} (Math)

SENSORS IN EXPRESSIONS:
Any active sensor name can be used as a variable in expressions."""
        },
        {
            "title": "Asynchronous Actions",
            "icon": "🧵",
            "content": """Complex actions (like long hardware commands) now run in the background.

This means:
• The application UI stays responsive and never freezes.
• Graphs continue to update while commands are being sent.
• Multiple sequences can execute actions simultaneously without blocking each other."""
        },
        {
            "title": "Available Actions",
            "icon": "🎬",
            "content": """HARDWARE COMMANDS:
• Arduino: Send custom serial strings
• LabJack: Set DAC voltages or Digital I/O
• MQTT: Publish messages to IoT topics
• Serial: Communicate with any connected serial device

SYSTEM ACTIONS:
• Recording: Start/Stop data collection
• Media: Take snapshots or play sounds
• Notification: Show popups or log messages

FLOW CONTROL:
• Set Variable: Store data for later
• Jump: Change execution order
• Condition: Logic-based branching"""
        },
        {
            "title": "Running Sequences",
            "icon": "▶️",
            "content": """TO RUN A SEQUENCE:
1. Select the sequence in the table
2. Click "Run Sequence" button
3. Monitor the status column for updates

SEQUENCE STATES:
🟢 Running: Sequence is active
🟡 Waiting: Waiting for trigger
🔴 Stopped: Manually stopped or completed
⚠️ Error: Problem occurred (check log)

STOPPING SEQUENCES:
• Click "Stop Sequence" to halt
• Sequences can auto-stop after completion
• Multiple sequences can run simultaneously

TIPS:
• Test sequences with low-risk actions first
• Use the error notifications to debug
• Check that connected devices are ready"""
        },
        {
            "title": "Time-lapse Videos",
            "icon": "🎥",
            "content": """CREATE TIME-LAPSE VIDEOS:
Combine snapshots from your media folder into smooth video.

SETTINGS:
• Source Folder: Where snapshots are stored
• Output File: Where to save the video
• Duration: Target video length
• FPS: Frames per second (smoothness)
• Format: MP4, AVI with various codecs

WORKFLOW:
1. Set up automated snapshots during experiment
2. After collection, use Time-lapse tool
3. Adjust settings for desired result
4. Click Create to generate video

TIPS:
• Higher FPS = smoother but shorter video
• MP4 (H.264) gives best compression
• Sort snapshots by timestamp for proper order"""
        }
    ]
}


CAMERA_HELP = {
    "title": "Camera & Video Help",
    "sections": [
        {
            "title": "NDI® Integration",
            "icon": "🌐",
            "content": """NDI (Network Device Interface) allows you to send and receive high-quality video over your local network.

NDI INPUT (Receive):
• Discovered NDI sources appear in the "Camera" dropdown prefixed with "NDI:".
• Select an NDI source and click "Connect" to use a remote camera or OBS stream as your video source.
• Overlays and motion detection work exactly like local USB cameras.

NDI OUTPUT (Send):
• Enable "NDI Output Settings" in the Camera settings popup.
• This broadcasts your current camera feed (with or without overlays) to the network.
• Professional software like OBS or vMix can pick up this feed instantly.

REQUIREMENTS:
• Ensure the NDI SDK is installed on your system.
• All devices must be on the same local network.
• Check your firewall settings if sources do not appear."""
        },
        {
            "title": "Recording & Overlays",
            "icon": "⏺️",
            "content": """RECORDING:
• Use the "Start Recording" button to save video.
• Recordings include all active overlays (sensor data, timestamps).
• Select between direct streaming (FFmpeg) or buffered recording in settings.

OVERLAYS:
• Right-click on the video feed to add text, sensor values, or motion boxes.
• Drag overlays to reposition them.
• Overlays are burned into the video during recording."""
        },
        {
            "title": "Motion Detection",
            "icon": "🔍",
            "content": """AUTOMATION TRIGGERS:
• Enable motion detection to trigger automation sequences.
• Adjust sensitivity and minimum area to filter out noise.
• Motion events are logged and can be used as start/stop triggers for data collection."""
        }
    ]
}


def get_help_content(tool_name: str) -> dict:
    """Get help content for a specific tool"""
    help_map = {
        "calibration": CALIBRATION_HELP,
        "fft": FFT_HELP,
        "statistics": STATISTICS_HELP,
        "diagnostics": DIAGNOSTICS_HELP,
        "calculator": CALCULATOR_HELP,
        "optical_sensor": OPTICAL_SENSOR_HELP,
        "audio_sensor": AUDIO_SENSOR_HELP,
        "automation": AUTOMATION_HELP,
        "sensors": SENSORS_HELP,
        "camera": CAMERA_HELP,
    }
    return help_map.get(tool_name, {"title": "Help", "sections": []})

