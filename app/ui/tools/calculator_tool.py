"""
Engineering Calculator Tool

Collection of useful calculators for DAQ and measurement applications:
- Unit Converter (Temperature, Pressure, etc.)
- RTD Calculator (PT100/PT1000)
- Thermocouple Tables
- Electrical Calculators (dB, Ohm's Law, Power)
- Frequency/Period Calculator
- Signal Scaling Calculator
"""

import numpy as np
from typing import Dict, Callable, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QDoubleSpinBox,
    QGroupBox, QFrame, QTabWidget, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# Import theme system
from app.ui.theme import GroupBoxStyles, CardStyles


class CalculatorCard(QFrame):
    """A styled card for a calculator section"""
    
    def __init__(self, title: str, icon: str = "🔢", parent=None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        
        self.setStyleSheet(CardStyles.elevated())
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(8)
        
        # Title
        title_label = QLabel(f"{icon} {title}")
        title_label.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 13px; border: none;")
        self.main_layout.addWidget(title_label)
        
        # Content area
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(5)
        self.main_layout.addLayout(self.content_layout)


class UnitConverterWidget(QWidget):
    """Unit converter with multiple categories"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._setup_conversions()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Category selection
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "Temperature", "Pressure", "Length", "Mass", 
            "Frequency", "Voltage", "Current", "Resistance"
        ])
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        cat_layout.addWidget(self.category_combo)
        cat_layout.addStretch()
        layout.addLayout(cat_layout)
        
        # Conversion area
        conv_frame = QFrame()
        conv_frame.setStyleSheet(CardStyles.default())
        conv_layout = QGridLayout(conv_frame)
        conv_layout.setSpacing(10)
        
        # Input
        conv_layout.addWidget(QLabel("From:"), 0, 0)
        self.input_value = QDoubleSpinBox()
        self.input_value.setRange(-1e12, 1e12)
        self.input_value.setDecimals(6)
        self.input_value.setValue(0)
        self.input_value.valueChanged.connect(self._convert)
        conv_layout.addWidget(self.input_value, 0, 1)
        
        self.input_unit = QComboBox()
        self.input_unit.setMinimumWidth(80)
        self.input_unit.currentIndexChanged.connect(self._convert)
        conv_layout.addWidget(self.input_unit, 0, 2)
        
        # Arrow
        arrow = QLabel("→")
        arrow.setStyleSheet("font-size: 20px; color: #4CAF50;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        conv_layout.addWidget(arrow, 0, 3)
        
        # Output
        conv_layout.addWidget(QLabel("To:"), 0, 4)
        self.output_value = QLineEdit()
        self.output_value.setReadOnly(True)
        self.output_value.setStyleSheet("background-color: #333; color: #4CAF50; font-weight: bold; padding: 5px;")
        conv_layout.addWidget(self.output_value, 0, 5)
        
        self.output_unit = QComboBox()
        self.output_unit.setMinimumWidth(80)
        self.output_unit.currentIndexChanged.connect(self._convert)
        conv_layout.addWidget(self.output_unit, 0, 6)
        
        layout.addWidget(conv_frame)
        
        # Quick reference table
        self.ref_table = QTableWidget()
        self.ref_table.setColumnCount(2)
        self.ref_table.setHorizontalHeaderLabels(["Unit", "Value"])
        self.ref_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ref_table.setStyleSheet("""
            QTableWidget { background-color: #222; color: #ddd; border: none; }
            QHeaderView::section { background-color: #333; color: #fff; padding: 5px; }
        """)
        self.ref_table.setMaximumHeight(200)
        layout.addWidget(self.ref_table)
    
    def _setup_conversions(self):
        """Setup conversion factors"""
        # All conversions are relative to a base unit
        self.conversions = {
            "Temperature": {
                "units": ["°C", "°F", "K"],
                "to_base": {  # to Celsius
                    "°C": lambda x: x,
                    "°F": lambda x: (x - 32) * 5/9,
                    "K": lambda x: x - 273.15
                },
                "from_base": {  # from Celsius
                    "°C": lambda x: x,
                    "°F": lambda x: x * 9/5 + 32,
                    "K": lambda x: x + 273.15
                }
            },
            "Pressure": {
                "units": ["Pa", "kPa", "MPa", "bar", "mbar", "psi", "atm", "mmHg", "inHg"],
                "factors": {  # to Pa
                    "Pa": 1, "kPa": 1000, "MPa": 1e6, "bar": 1e5, "mbar": 100,
                    "psi": 6894.76, "atm": 101325, "mmHg": 133.322, "inHg": 3386.39
                }
            },
            "Length": {
                "units": ["m", "cm", "mm", "μm", "nm", "km", "in", "ft", "yd", "mi"],
                "factors": {  # to m
                    "m": 1, "cm": 0.01, "mm": 0.001, "μm": 1e-6, "nm": 1e-9,
                    "km": 1000, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.34
                }
            },
            "Mass": {
                "units": ["kg", "g", "mg", "μg", "lb", "oz", "ton"],
                "factors": {  # to kg
                    "kg": 1, "g": 0.001, "mg": 1e-6, "μg": 1e-9,
                    "lb": 0.453592, "oz": 0.0283495, "ton": 1000
                }
            },
            "Frequency": {
                "units": ["Hz", "kHz", "MHz", "GHz", "rpm", "rad/s"],
                "factors": {  # to Hz
                    "Hz": 1, "kHz": 1000, "MHz": 1e6, "GHz": 1e9,
                    "rpm": 1/60, "rad/s": 1/(2*np.pi)
                }
            },
            "Voltage": {
                "units": ["V", "mV", "μV", "kV"],
                "factors": {"V": 1, "mV": 0.001, "μV": 1e-6, "kV": 1000}
            },
            "Current": {
                "units": ["A", "mA", "μA", "nA"],
                "factors": {"A": 1, "mA": 0.001, "μA": 1e-6, "nA": 1e-9}
            },
            "Resistance": {
                "units": ["Ω", "mΩ", "kΩ", "MΩ"],
                "factors": {"Ω": 1, "mΩ": 0.001, "kΩ": 1000, "MΩ": 1e6}
            }
        }
        
        # Initialize with first category
        self._on_category_changed()
    
    def _on_category_changed(self):
        """Handle category change"""
        category = self.category_combo.currentText()
        conv = self.conversions.get(category, {})
        units = conv.get("units", [])
        
        self.input_unit.clear()
        self.input_unit.addItems(units)
        
        self.output_unit.clear()
        self.output_unit.addItems(units)
        if len(units) > 1:
            self.output_unit.setCurrentIndex(1)
        
        self._convert()
    
    def _convert(self):
        """Perform conversion"""
        category = self.category_combo.currentText()
        conv = self.conversions.get(category, {})
        
        input_val = self.input_value.value()
        from_unit = self.input_unit.currentText()
        to_unit = self.output_unit.currentText()
        
        if not from_unit or not to_unit:
            return
        
        # Temperature has special handling
        if category == "Temperature":
            to_base = conv["to_base"]
            from_base = conv["from_base"]
            base_val = to_base[from_unit](input_val)
            result = from_base[to_unit](base_val)
        else:
            factors = conv.get("factors", {})
            if from_unit in factors and to_unit in factors:
                base_val = input_val * factors[from_unit]
                result = base_val / factors[to_unit]
            else:
                result = input_val
        
        self.output_value.setText(f"{result:.6g}")
        self._update_reference_table(category, input_val, from_unit, conv)
    
    def _update_reference_table(self, category, value, from_unit, conv):
        """Update reference table with all unit conversions"""
        units = conv.get("units", [])
        self.ref_table.setRowCount(len(units))
        
        for i, unit in enumerate(units):
            self.ref_table.setItem(i, 0, QTableWidgetItem(unit))
            
            if category == "Temperature":
                base_val = conv["to_base"][from_unit](value)
                result = conv["from_base"][unit](base_val)
            else:
                factors = conv.get("factors", {})
                base_val = value * factors.get(from_unit, 1)
                result = base_val / factors.get(unit, 1)
            
            self.ref_table.setItem(i, 1, QTableWidgetItem(f"{result:.6g}"))


class RTDCalculatorWidget(QWidget):
    """PT100/PT1000/NTC Calculator"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # RTD Type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("RTD Type:"))
        self.rtd_type = QComboBox()
        self.rtd_type.addItems(["PT100", "PT1000", "NTC 10kΩ", "NTC 100kΩ"])
        self.rtd_type.currentIndexChanged.connect(self._calculate)
        type_layout.addWidget(self.rtd_type)
        type_layout.addStretch()
        layout.addLayout(type_layout)
        
        # Calculation direction
        dir_group = QGroupBox("Calculation Direction")
        dir_group.setStyleSheet(GroupBoxStyles.compact())
        dir_layout = QHBoxLayout(dir_group)
        
        self.dir_button_group = QButtonGroup()
        
        self.temp_to_res = QRadioButton("Temperature → Resistance")
        self.temp_to_res.setChecked(True)
        self.temp_to_res.setStyleSheet("color: #ccc;")
        self.dir_button_group.addButton(self.temp_to_res, 0)
        dir_layout.addWidget(self.temp_to_res)
        
        self.res_to_temp = QRadioButton("Resistance → Temperature")
        self.res_to_temp.setStyleSheet("color: #ccc;")
        self.dir_button_group.addButton(self.res_to_temp, 1)
        dir_layout.addWidget(self.res_to_temp)
        
        self.dir_button_group.buttonClicked.connect(self._on_direction_changed)
        layout.addWidget(dir_group)
        
        # Input/Output
        io_frame = QFrame()
        io_frame.setStyleSheet(CardStyles.default())
        io_layout = QGridLayout(io_frame)
        io_layout.setSpacing(10)
        
        # Input
        self.input_label = QLabel("Temperature (°C):")
        io_layout.addWidget(self.input_label, 0, 0)
        self.input_spin = QDoubleSpinBox()
        self.input_spin.setRange(-200, 850)
        self.input_spin.setDecimals(2)
        self.input_spin.setValue(25)
        self.input_spin.valueChanged.connect(self._calculate)
        io_layout.addWidget(self.input_spin, 0, 1)
        
        # Arrow
        arrow = QLabel("→")
        arrow.setStyleSheet("font-size: 20px; color: #4CAF50;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        io_layout.addWidget(arrow, 0, 2)
        
        # Output
        self.output_label = QLabel("Resistance (Ω):")
        io_layout.addWidget(self.output_label, 0, 3)
        self.output_field = QLineEdit()
        self.output_field.setReadOnly(True)
        self.output_field.setStyleSheet("background-color: #333; color: #4CAF50; font-weight: bold; font-size: 14px; padding: 5px;")
        io_layout.addWidget(self.output_field, 0, 4)
        
        layout.addWidget(io_frame)
        
        # Reference table
        ref_label = QLabel("Reference Table:")
        ref_label.setStyleSheet("color: #888;")
        layout.addWidget(ref_label)
        
        self.ref_table = QTableWidget()
        self.ref_table.setColumnCount(2)
        self.ref_table.setHorizontalHeaderLabels(["Temperature (°C)", "Resistance (Ω)"])
        self.ref_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ref_table.setStyleSheet("""
            QTableWidget { background-color: #222; color: #ddd; border: none; }
            QHeaderView::section { background-color: #333; color: #fff; padding: 5px; }
        """)
        layout.addWidget(self.ref_table)
        
        self._calculate()
    
    def _on_direction_changed(self):
        """Handle direction change"""
        if self.temp_to_res.isChecked():
            self.input_label.setText("Temperature (°C):")
            self.output_label.setText("Resistance (Ω):")
            self.input_spin.setRange(-200, 850)
            self.input_spin.setValue(25)
        else:
            self.input_label.setText("Resistance (Ω):")
            self.output_label.setText("Temperature (°C):")
            rtd_type = self.rtd_type.currentText()
            if "PT100" in rtd_type:
                self.input_spin.setRange(0, 400)
                self.input_spin.setValue(100)
            elif "PT1000" in rtd_type:
                self.input_spin.setRange(0, 4000)
                self.input_spin.setValue(1000)
            else:  # NTC
                self.input_spin.setRange(0, 1000000)
                self.input_spin.setValue(10000)
        
        self._calculate()
    
    def _calculate(self):
        """Perform RTD calculation"""
        rtd_type = self.rtd_type.currentText()
        value = self.input_spin.value()
        
        if self.temp_to_res.isChecked():
            result = self._temp_to_resistance(rtd_type, value)
            self.output_field.setText(f"{result:.4f} Ω")
        else:
            result = self._resistance_to_temp(rtd_type, value)
            self.output_field.setText(f"{result:.2f} °C")
        
        self._update_reference_table(rtd_type)
    
    def _temp_to_resistance(self, rtd_type: str, temp: float) -> float:
        """Calculate resistance from temperature"""
        if "PT100" in rtd_type:
            R0 = 100
        elif "PT1000" in rtd_type:
            R0 = 1000
        else:  # NTC
            R0 = 10000 if "10k" in rtd_type else 100000
            B = 3950  # Typical B constant
            T0 = 298.15  # 25°C in Kelvin
            T = temp + 273.15
            return R0 * np.exp(B * (1/T - 1/T0))
        
        # PT RTD Callendar-Van Dusen equation
        A = 3.9083e-3
        B = -5.775e-7
        
        if temp >= 0:
            return R0 * (1 + A * temp + B * temp**2)
        else:
            C = -4.183e-12
            return R0 * (1 + A * temp + B * temp**2 + C * (temp - 100) * temp**3)
    
    def _resistance_to_temp(self, rtd_type: str, resistance: float) -> float:
        """Calculate temperature from resistance"""
        if "PT100" in rtd_type:
            R0 = 100
        elif "PT1000" in rtd_type:
            R0 = 1000
        else:  # NTC
            R0 = 10000 if "10k" in rtd_type else 100000
            B = 3950
            T0 = 298.15
            if resistance <= 0:
                return -273.15
            T = 1 / (1/T0 + (1/B) * np.log(resistance/R0))
            return T - 273.15
        
        # PT RTD inverse calculation (approximation)
        A = 3.9083e-3
        B = -5.775e-7
        
        # Quadratic formula solution
        r_ratio = resistance / R0
        discriminant = A**2 - 4 * B * (1 - r_ratio)
        
        if discriminant < 0:
            return -273.15  # Invalid
        
        temp = (-A + np.sqrt(discriminant)) / (2 * B)
        return temp
    
    def _update_reference_table(self, rtd_type: str):
        """Update reference table"""
        temps = [-50, -25, 0, 25, 50, 75, 100, 150, 200, 300]
        self.ref_table.setRowCount(len(temps))
        
        for i, temp in enumerate(temps):
            self.ref_table.setItem(i, 0, QTableWidgetItem(f"{temp}"))
            resistance = self._temp_to_resistance(rtd_type, temp)
            self.ref_table.setItem(i, 1, QTableWidgetItem(f"{resistance:.2f}"))


class ElectricalCalculatorWidget(QWidget):
    """Electrical calculators (Ohm's Law, dB, Power)"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        # Ohm's Law Calculator
        ohm_card = CalculatorCard("Ohm's Law (V = I × R)", "⚡")
        ohm_grid = QGridLayout()
        ohm_grid.setSpacing(5)
        
        # Voltage
        ohm_grid.addWidget(QLabel("Voltage (V):"), 0, 0)
        self.voltage_spin = QDoubleSpinBox()
        self.voltage_spin.setRange(0, 1e9)
        self.voltage_spin.setDecimals(4)
        self.voltage_spin.setValue(5)
        self.voltage_spin.valueChanged.connect(lambda: self._calc_ohm("V"))
        ohm_grid.addWidget(self.voltage_spin, 0, 1)
        
        self.calc_v_btn = QPushButton("Calculate V")
        self.calc_v_btn.setStyleSheet("background-color: #1565C0; color: white; border: none; border-radius: 3px; padding: 3px;")
        self.calc_v_btn.clicked.connect(lambda: self._calc_ohm("calc_V"))
        ohm_grid.addWidget(self.calc_v_btn, 0, 2)
        
        # Current
        ohm_grid.addWidget(QLabel("Current (A):"), 1, 0)
        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0, 1e9)
        self.current_spin.setDecimals(6)
        self.current_spin.setValue(0.001)
        self.current_spin.valueChanged.connect(lambda: self._calc_ohm("I"))
        ohm_grid.addWidget(self.current_spin, 1, 1)
        
        self.calc_i_btn = QPushButton("Calculate I")
        self.calc_i_btn.setStyleSheet("background-color: #1565C0; color: white; border: none; border-radius: 3px; padding: 3px;")
        self.calc_i_btn.clicked.connect(lambda: self._calc_ohm("calc_I"))
        ohm_grid.addWidget(self.calc_i_btn, 1, 2)
        
        # Resistance
        ohm_grid.addWidget(QLabel("Resistance (Ω):"), 2, 0)
        self.resistance_spin = QDoubleSpinBox()
        self.resistance_spin.setRange(0, 1e12)
        self.resistance_spin.setDecimals(4)
        self.resistance_spin.setValue(5000)
        self.resistance_spin.valueChanged.connect(lambda: self._calc_ohm("R"))
        ohm_grid.addWidget(self.resistance_spin, 2, 1)
        
        self.calc_r_btn = QPushButton("Calculate R")
        self.calc_r_btn.setStyleSheet("background-color: #1565C0; color: white; border: none; border-radius: 3px; padding: 3px;")
        self.calc_r_btn.clicked.connect(lambda: self._calc_ohm("calc_R"))
        ohm_grid.addWidget(self.calc_r_btn, 2, 2)
        
        # Power result
        ohm_grid.addWidget(QLabel("Power (W):"), 3, 0)
        self.power_label = QLabel("0.005 W")
        self.power_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        ohm_grid.addWidget(self.power_label, 3, 1)
        
        ohm_card.content_layout.addLayout(ohm_grid)
        layout.addWidget(ohm_card)
        
        # dB Calculator
        db_card = CalculatorCard("dB Calculator", "📊")
        db_grid = QGridLayout()
        db_grid.setSpacing(5)
        
        # Ratio to dB
        db_grid.addWidget(QLabel("Ratio:"), 0, 0)
        self.ratio_spin = QDoubleSpinBox()
        self.ratio_spin.setRange(0.000001, 1e12)
        self.ratio_spin.setDecimals(6)
        self.ratio_spin.setValue(2)
        self.ratio_spin.valueChanged.connect(self._calc_db_from_ratio)
        db_grid.addWidget(self.ratio_spin, 0, 1)
        
        db_grid.addWidget(QLabel("→"), 0, 2)
        
        self.db_from_ratio = QLineEdit()
        self.db_from_ratio.setReadOnly(True)
        self.db_from_ratio.setStyleSheet("background-color: #333; color: #4CAF50; font-weight: bold;")
        db_grid.addWidget(self.db_from_ratio, 0, 3)
        db_grid.addWidget(QLabel("dB"), 0, 4)
        
        # dB type
        self.db_type_combo = QComboBox()
        self.db_type_combo.addItems(["Power (10×log)", "Voltage (20×log)"])
        self.db_type_combo.currentIndexChanged.connect(self._calc_db_from_ratio)
        db_grid.addWidget(self.db_type_combo, 0, 5)
        
        # dB to Ratio
        db_grid.addWidget(QLabel("dB:"), 1, 0)
        self.db_spin = QDoubleSpinBox()
        self.db_spin.setRange(-200, 200)
        self.db_spin.setDecimals(2)
        self.db_spin.setValue(3)
        self.db_spin.valueChanged.connect(self._calc_ratio_from_db)
        db_grid.addWidget(self.db_spin, 1, 1)
        
        db_grid.addWidget(QLabel("→"), 1, 2)
        
        self.ratio_from_db = QLineEdit()
        self.ratio_from_db.setReadOnly(True)
        self.ratio_from_db.setStyleSheet("background-color: #333; color: #4CAF50; font-weight: bold;")
        db_grid.addWidget(self.ratio_from_db, 1, 3)
        db_grid.addWidget(QLabel("×"), 1, 4)
        
        db_card.content_layout.addLayout(db_grid)
        layout.addWidget(db_card)
        
        # Frequency/Period Calculator
        freq_card = CalculatorCard("Frequency ↔ Period", "〰️")
        freq_grid = QGridLayout()
        freq_grid.setSpacing(5)
        
        freq_grid.addWidget(QLabel("Frequency:"), 0, 0)
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(0.000001, 1e12)
        self.freq_spin.setDecimals(6)
        self.freq_spin.setValue(1000)
        self.freq_spin.valueChanged.connect(self._calc_period_from_freq)
        freq_grid.addWidget(self.freq_spin, 0, 1)
        
        self.freq_unit = QComboBox()
        self.freq_unit.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.freq_unit.currentIndexChanged.connect(self._calc_period_from_freq)
        freq_grid.addWidget(self.freq_unit, 0, 2)
        
        freq_grid.addWidget(QLabel("↔"), 0, 3)
        
        freq_grid.addWidget(QLabel("Period:"), 0, 4)
        self.period_result = QLineEdit()
        self.period_result.setReadOnly(True)
        self.period_result.setStyleSheet("background-color: #333; color: #4CAF50; font-weight: bold;")
        freq_grid.addWidget(self.period_result, 0, 5)
        
        freq_card.content_layout.addLayout(freq_grid)
        layout.addWidget(freq_card)
        
        layout.addStretch()
        
        # Initialize calculations
        self._calc_ohm("V")
        self._calc_db_from_ratio()
        self._calc_period_from_freq()
    
    def _calc_ohm(self, source: str):
        """Calculate Ohm's law"""
        V = self.voltage_spin.value()
        I = self.current_spin.value()
        R = self.resistance_spin.value()
        
        if source == "calc_V" and I > 0 and R > 0:
            V = I * R
            self.voltage_spin.blockSignals(True)
            self.voltage_spin.setValue(V)
            self.voltage_spin.blockSignals(False)
        elif source == "calc_I" and V > 0 and R > 0:
            I = V / R
            self.current_spin.blockSignals(True)
            self.current_spin.setValue(I)
            self.current_spin.blockSignals(False)
        elif source == "calc_R" and V > 0 and I > 0:
            R = V / I
            self.resistance_spin.blockSignals(True)
            self.resistance_spin.setValue(R)
            self.resistance_spin.blockSignals(False)
        
        # Calculate power
        P = V * I
        if P < 0.001:
            self.power_label.setText(f"{P*1e6:.3f} μW")
        elif P < 1:
            self.power_label.setText(f"{P*1e3:.3f} mW")
        elif P < 1000:
            self.power_label.setText(f"{P:.4f} W")
        else:
            self.power_label.setText(f"{P/1000:.3f} kW")
    
    def _calc_db_from_ratio(self):
        """Calculate dB from ratio"""
        ratio = self.ratio_spin.value()
        is_power = "Power" in self.db_type_combo.currentText()
        
        if ratio > 0:
            multiplier = 10 if is_power else 20
            db = multiplier * np.log10(ratio)
            self.db_from_ratio.setText(f"{db:.3f}")
    
    def _calc_ratio_from_db(self):
        """Calculate ratio from dB"""
        db = self.db_spin.value()
        is_power = "Power" in self.db_type_combo.currentText()
        
        multiplier = 10 if is_power else 20
        ratio = 10 ** (db / multiplier)
        self.ratio_from_db.setText(f"{ratio:.6g}")
    
    def _calc_period_from_freq(self):
        """Calculate period from frequency"""
        freq = self.freq_spin.value()
        unit = self.freq_unit.currentText()
        
        # Convert to Hz
        multipliers = {"Hz": 1, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}
        freq_hz = freq * multipliers.get(unit, 1)
        
        if freq_hz > 0:
            period = 1 / freq_hz
            
            if period < 1e-9:
                self.period_result.setText(f"{period*1e12:.3f} ps")
            elif period < 1e-6:
                self.period_result.setText(f"{period*1e9:.3f} ns")
            elif period < 1e-3:
                self.period_result.setText(f"{period*1e6:.3f} μs")
            elif period < 1:
                self.period_result.setText(f"{period*1e3:.3f} ms")
            else:
                self.period_result.setText(f"{period:.6f} s")


class SignalScalingWidget(QWidget):
    """Signal scaling/conversion calculator"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        info_label = QLabel("Calculate scaling factors for sensor signals (y = mx + b)")
        info_label.setStyleSheet("color: #888;")
        layout.addWidget(info_label)
        
        # Input range
        input_card = CalculatorCard("Input Signal Range", "📥")
        input_grid = QGridLayout()
        
        input_grid.addWidget(QLabel("Min:"), 0, 0)
        self.input_min = QDoubleSpinBox()
        self.input_min.setRange(-1e12, 1e12)
        self.input_min.setDecimals(6)
        self.input_min.setValue(0)
        self.input_min.valueChanged.connect(self._calculate)
        input_grid.addWidget(self.input_min, 0, 1)
        
        self.input_unit = QLineEdit("V")
        self.input_unit.setMaximumWidth(50)
        input_grid.addWidget(self.input_unit, 0, 2)
        
        input_grid.addWidget(QLabel("Max:"), 0, 3)
        self.input_max = QDoubleSpinBox()
        self.input_max.setRange(-1e12, 1e12)
        self.input_max.setDecimals(6)
        self.input_max.setValue(5)
        self.input_max.valueChanged.connect(self._calculate)
        input_grid.addWidget(self.input_max, 0, 4)
        
        input_card.content_layout.addLayout(input_grid)
        layout.addWidget(input_card)
        
        # Output range
        output_card = CalculatorCard("Output/Physical Range", "📤")
        output_grid = QGridLayout()
        
        output_grid.addWidget(QLabel("Min:"), 0, 0)
        self.output_min = QDoubleSpinBox()
        self.output_min.setRange(-1e12, 1e12)
        self.output_min.setDecimals(6)
        self.output_min.setValue(0)
        self.output_min.valueChanged.connect(self._calculate)
        output_grid.addWidget(self.output_min, 0, 1)
        
        self.output_unit = QLineEdit("°C")
        self.output_unit.setMaximumWidth(50)
        output_grid.addWidget(self.output_unit, 0, 2)
        
        output_grid.addWidget(QLabel("Max:"), 0, 3)
        self.output_max = QDoubleSpinBox()
        self.output_max.setRange(-1e12, 1e12)
        self.output_max.setDecimals(6)
        self.output_max.setValue(100)
        self.output_max.valueChanged.connect(self._calculate)
        output_grid.addWidget(self.output_max, 0, 4)
        
        output_card.content_layout.addLayout(output_grid)
        layout.addWidget(output_card)
        
        # Results
        result_card = CalculatorCard("Scaling Factors", "🔢")
        result_grid = QGridLayout()
        
        result_grid.addWidget(QLabel("Slope (m):"), 0, 0)
        self.slope_label = QLabel("--")
        self.slope_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        result_grid.addWidget(self.slope_label, 0, 1)
        
        result_grid.addWidget(QLabel("Offset (b):"), 1, 0)
        self.offset_label = QLabel("--")
        self.offset_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        result_grid.addWidget(self.offset_label, 1, 1)
        
        result_grid.addWidget(QLabel("Formula:"), 2, 0)
        self.formula_label = QLabel("y = m × x + b")
        self.formula_label.setStyleSheet("color: #FFC107; font-weight: bold;")
        result_grid.addWidget(self.formula_label, 2, 1)
        
        result_card.content_layout.addLayout(result_grid)
        layout.addWidget(result_card)
        
        # Test conversion
        test_card = CalculatorCard("Test Conversion", "🧪")
        test_grid = QGridLayout()
        
        test_grid.addWidget(QLabel("Input Value:"), 0, 0)
        self.test_input = QDoubleSpinBox()
        self.test_input.setRange(-1e12, 1e12)
        self.test_input.setDecimals(6)
        self.test_input.setValue(2.5)
        self.test_input.valueChanged.connect(self._test_convert)
        test_grid.addWidget(self.test_input, 0, 1)
        
        test_grid.addWidget(QLabel("→"), 0, 2)
        
        test_grid.addWidget(QLabel("Output:"), 0, 3)
        self.test_output = QLabel("--")
        self.test_output.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
        test_grid.addWidget(self.test_output, 0, 4)
        
        test_card.content_layout.addLayout(test_grid)
        layout.addWidget(test_card)
        
        layout.addStretch()
        self._calculate()
    
    def _calculate(self):
        """Calculate scaling factors"""
        in_min = self.input_min.value()
        in_max = self.input_max.value()
        out_min = self.output_min.value()
        out_max = self.output_max.value()
        
        in_range = in_max - in_min
        out_range = out_max - out_min
        
        if in_range == 0:
            self.slope_label.setText("Error: Input range is 0")
            self.offset_label.setText("--")
            return
        
        slope = out_range / in_range
        offset = out_min - slope * in_min
        
        self.slope_label.setText(f"{slope:.6g}")
        self.offset_label.setText(f"{offset:.6g}")
        
        in_unit = self.input_unit.text()
        out_unit = self.output_unit.text()
        self.formula_label.setText(f"{out_unit} = {slope:.4g} × {in_unit} + {offset:.4g}")
        
        self._test_convert()
    
    def _test_convert(self):
        """Test the conversion"""
        in_min = self.input_min.value()
        in_max = self.input_max.value()
        out_min = self.output_min.value()
        out_max = self.output_max.value()
        
        in_range = in_max - in_min
        if in_range == 0:
            return
        
        slope = (out_max - out_min) / in_range
        offset = out_min - slope * in_min
        
        test_val = self.test_input.value()
        result = slope * test_val + offset
        
        out_unit = self.output_unit.text()
        self.test_output.setText(f"{result:.4g} {out_unit}")


class CalculatorTool(QWidget):
    """Main Calculator Tool with tabs for different calculators"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self._setup_ui()
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Header
        title = QLabel("📐 Engineering Calculator")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #9C27B0;")
        layout.addWidget(title)
        
        # Container to constrain tab widget width
        tab_container = QWidget()
        tab_container_layout = QHBoxLayout(tab_container)
        tab_container_layout.setContentsMargins(0, 0, 0, 0)
        tab_container_layout.addStretch()
        
        # Tab widget with maximum width constraint
        tabs = QTabWidget()
        tabs.setMaximumWidth(800)  # Limit maximum width
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444;
                border-radius: 6px;
                background-color: #1a1a2e;
            }
            QTabBar::tab {
                background-color: #2d2d44;
                color: #aaa;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #3d3d5c;
                color: #fff;
            }
        """)
        
        # Constrain tab bar width to prevent stretching
        tab_bar = tabs.tabBar()
        tab_bar.setExpanding(False)
        
        # Unit Converter
        tabs.addTab(UnitConverterWidget(), "🔄 Unit Converter")
        
        # RTD Calculator
        tabs.addTab(RTDCalculatorWidget(), "🌡️ RTD / NTC")
        
        # Electrical Calculator
        tabs.addTab(ElectricalCalculatorWidget(), "⚡ Electrical")
        
        # Signal Scaling
        tabs.addTab(SignalScalingWidget(), "📊 Signal Scaling")
        
        tab_container_layout.addWidget(tabs)
        tab_container_layout.addStretch()
        
        layout.addWidget(tab_container)
    
    def stop(self):
        """Stop method for consistency"""
        pass

