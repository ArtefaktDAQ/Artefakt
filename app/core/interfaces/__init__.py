# Hardware interfaces package 

from app.core.interfaces.base_interface import BaseInterface
from app.core.interfaces.arduino_interface import ArduinoInterface
from app.core.interfaces.arduino_master_slave import ArduinoMasterSlaveThread
from app.core.interfaces.ndi_interface import NDIInterface, NDI_AVAILABLE

# Conditional LabJack import - library may not be available on all platforms
from app.core.interfaces.labjack_interface import LabJackInterface, LABJACK_AVAILABLE

# Optical Sensor (Camera as sensor)
from app.core.interfaces.optical_sensor_interface import (
    OpticalSensorInterface, 
    OpticalSensorThread,
    OPTICAL_SENSOR_AVAILABLE
)

# Audio Sensor (Microphone as sensor)
from app.core.interfaces.audio_interface import (
    AudioSensorInterface,
    AudioSensorThread,
    AUDIO_SENSOR_AVAILABLE
)

__all__ = [
    'BaseInterface', 
    'ArduinoInterface', 
    'ArduinoMasterSlaveThread', 
    'LabJackInterface',
    'LABJACK_AVAILABLE',
    'NDIInterface',
    'NDI_AVAILABLE',
    'OpticalSensorInterface',
    'OpticalSensorThread',
    'OPTICAL_SENSOR_AVAILABLE',
    'AudioSensorInterface',
    'AudioSensorThread',
    'AUDIO_SENSOR_AVAILABLE'
]
