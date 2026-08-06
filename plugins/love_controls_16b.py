from app.core.interfaces.base_interface import BaseInterface
import serial
import struct
import time
import logging

logger = logging.getLogger(__name__)

class Dwyer16B(BaseInterface):
    """
    Plugin for Dwyer16B Temperature Controller using Modbus ASCII/RTU.
    Aligned with working pymodbus script.
    """
    
    DISPLAY_NAME = "Dwyer16B"
    DESCRIPTION = "Modbus ASCII/RTU interface for Dwyer16B Series Temperature Controllers."
    ICON = "🌡️"
    
    CONFIG_SCHEMA = {
        "port": {
            "type": "list", 
            "label": "Serial Port", 
            "options_cmd": "list_ports",
            "required": True
        },
        "baud_rate": {
            "type": "list", 
            "label": "Baud Rate", 
            "options": [4800, 9600, 19200, 38400], 
            "default": 9600
        },
        "protocol": {
            "type": "list",
            "label": "Protocol",
            "options": ["RTU", "ASCII"],
            "default": "RTU"
        },
        "parity": {
            "type": "list",
            "label": "Parity",
            "options": ["None", "Even", "Odd"],
            "default": "Even"
        },
        "modbus_id": {
            "type": "number", 
            "label": "Modbus ID", 
            "default": 1
        },
        "pv_register": {
            "type": "string",
            "label": "PV Register (e.g. 0, 1000H or 4096)",
            "default": "1000H"
        },
        "sv_register": {
            "type": "string",
            "label": "SV Register (e.g. 1, 1000H or 4096)",
            "default": "1001H"
        },
        "decimal_places": {
            "type": "number", 
            "label": "Decimal Places", 
            "default": 1
        },
        "poll_rate": {
            "type": "number", 
            "label": "Poll Rate (Hz)", 
            "default": 1.0
        }
    }

    def __init__(
        self,
        port="COM1",
        baud_rate=9600,
        protocol="RTU",
        data_bits=8,
        parity="Even",
        stop_bits=1,
        modbus_id=1,
        decimal_places=1,
        pv_register="0",
        sv_register="1",
        **kwargs,
    ):
        super().__init__(name="Dwyer16B")
        import threading
        self.lock = threading.Lock()
        self.port = port
        self.baud_rate = int(baud_rate)
        self.protocol = str(protocol).strip().upper()
        self.data_bits = int(data_bits)
        self.parity = str(parity)
        self.stop_bits = int(stop_bits)
        self.modbus_id = int(modbus_id)
        self.decimal_places_val = int(decimal_places)
        self.serial = None
        self.error_message = ""
        
        # Store these as strings so they can be updated by the UI
        self.pv_register = str(pv_register)
        self.sv_register = str(sv_register)

    @property
    def decimal_places(self):
        try:
            return int(self.decimal_places_val)
        except (ValueError, TypeError):
            return 1

    @decimal_places.setter
    def decimal_places(self, value):
        self.decimal_places_val = value

    @property
    def REG_PV(self):
        return self._parse_register(self.pv_register)

    @property
    def REG_SV(self):
        return self._parse_register(self.sv_register)

    @classmethod
    def get_output_keys(cls):
        return ["Temperature", "Setpoint"]

    @classmethod
    def get_test_actions(cls):
        return [
            {
                "id": "read_snapshot",
                "label": "Test Read PV/SV",
            },
            {
                "id": "write_setpoint",
                "label": "Test Write Setpoint",
                "input_label": "Setpoint (°C)",
                "default_value": "20.0",
            },
        ]

    @classmethod
    def get_ui_options(cls, field_name):
        if field_name == "port":
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
        return []

    def connect(self):
        with self.lock:
            try:
                # Force a clean start: close existing serial if it exists
                if self.serial:
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                    self.serial = None

                self.serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baud_rate,
                    bytesize=serial.EIGHTBITS if self.data_bits == 8 else serial.SEVENBITS,
                    parity=self._get_parity_constant(),
                    stopbits=serial.STOPBITS_ONE if self.stop_bits == 1 else serial.STOPBITS_TWO,
                    timeout=1.0,
                    write_timeout=1.0
                )
                self.connected = True
                logger.info(f"Connected to Dwyer16B on {self.port} at {self.baud_rate} baud")
                return True
            except Exception as e:
                self.connected = False
                self.error_message = str(e)
                if self.serial:
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
                logger.error(f"Failed to connect to Dwyer16B on {self.port}: {e}")
                return False

    def disconnect(self):
        with self.lock:
            self.connected = False
            if self.serial:
                try:
                    logger.info(f"Disconnecting Dwyer16B on {self.port}")
                    self.serial.close()
                except Exception as e:
                    logger.error(f"Error closing serial port {self.port}: {e}")
                finally:
                    self.serial = None

    def is_connected(self):
        with self.lock:
            if not self.serial:
                self.connected = False
                return False

            try:
                if not self.serial.is_open:
                    self.connected = False
                    return False
                # A lightweight pyserial call catches unplugged adapters sooner
                # than checking the stale boolean alone.
                _ = self.serial.in_waiting
            except Exception as e:
                self.connected = False
                self.error_message = str(e)
                try:
                    self.serial.close()
                except Exception:
                    pass
                self.serial = None
                return False

            self.connected = True
            return True

    def _get_parity_constant(self):
        parity_map = {
            "NONE": serial.PARITY_NONE,
            "EVEN": serial.PARITY_EVEN,
            "ODD": serial.PARITY_ODD,
        }
        return parity_map.get(self.parity.strip().upper(), serial.PARITY_NONE)

    def _parse_register(self, value):
        if isinstance(value, str):
            text = value.strip().upper()
            if text.endswith("H"):
                core = text[:-1]
                try:
                    return int(core, 16)
                except ValueError:
                    return 1000
            if text.startswith("0X"):
                try:
                    return int(text, 16)
                except ValueError:
                    return 1000
        try:
            return int(value)
        except (ValueError, TypeError):
            return 1000

    def _wire_address(self, register_number):
        # Working script uses register number directly as PDU address
        return int(register_number)

    def _calculate_crc(self, data):
        crc = 0xFFFF
        for pos in data:
            crc ^= pos
            for i in range(8):
                if (crc & 1) != 0:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _calculate_lrc(self, data):
        return ((-sum(data)) & 0xFF)

    def _build_ascii_frame(self, payload):
        lrc = self._calculate_lrc(payload)
        return f":{payload.hex().upper()}{lrc:02X}\r\n".encode("ascii")

    def _send_rtu_request(self, function_code, address, value_or_count):
        # modbus_id must be an integer
        modbus_id = int(self.modbus_id)
        packet = struct.pack('>BBHH', modbus_id, function_code, address, value_or_count)
        packet += self._calculate_crc(packet)

        # Physically send the packet to the serial port
        self.serial.write(packet)
        self.serial.flush()

        if function_code == 0x03 or function_code == 0x04:
            expected_len = 5 + (value_or_count * 2)
        else:
            expected_len = 8

        deadline = time.monotonic() + getattr(self.serial, 'timeout', 1.0)
        response = bytearray()
        while len(response) < expected_len and time.monotonic() < deadline:
            chunk = self.serial.read(expected_len - len(response))
            if chunk:
                response.extend(chunk)
        response = bytes(response)

        if len(response) == 5 and response[1] == (function_code | 0x80):
            exception_code = response[2]
            reason = {
                0x01: "Illegal Function",
                0x02: "Illegal Data Address",
                0x03: "Illegal Data Value",
                0x04: "Slave Device Failure"
            }.get(exception_code, "Unknown Exception")
            
            self.error_message = (
                f"Modbus exception 0x{exception_code:02X} ({reason}) "
                f"for function=0x{function_code:02X}, address={address}"
            )
            logger.error(
                f"Modbus exception from ID {modbus_id} on {self.port}: "
                f"function=0x{function_code:02X}, address={address} (0x{address:04X}), "
                f"exception=0x{exception_code:02X} ({reason})"
            )
            return None

        if len(response) >= expected_len:
            resp_crc = response[expected_len-2:expected_len]
            calc_crc = self._calculate_crc(response[:expected_len-2])
            if resp_crc == calc_crc:
                return response[:expected_len-2]

            logger.warning(f"Modbus CRC mismatch on {self.port}. Expected {calc_crc.hex()}, got {resp_crc.hex()}")
            return None

        if len(response) == 0:
            logger.debug(f"Modbus timeout: No response from ID {modbus_id} on {self.port} (expected {expected_len} bytes)")
        else:
            logger.debug(f"Modbus short response: {len(response)}/{expected_len} bytes on {self.port}: {response.hex()}")
        return None

    def _send_ascii_request(self, function_code, address, value_or_count):
        payload = struct.pack(">BBHH", self.modbus_id, function_code, address, value_or_count)
        frame = self._build_ascii_frame(payload)
        self.serial.write(frame)
        self.serial.flush()

        response = self.serial.read_until(b"\n")
        if not response:
            logger.warning(f"Modbus ASCII timeout: No response from ID {self.modbus_id} on {self.port}")
            return None

        response = response.strip()
        if not response.startswith(b":"):
            logger.warning(f"Modbus ASCII invalid response on {self.port}: {response!r}")
            return None

        try:
            decoded = bytes.fromhex(response[1:].decode("ascii"))
        except Exception:
            logger.warning(f"Modbus ASCII undecodable response on {self.port}: {response!r}")
            return None

        if len(decoded) < 4:
            logger.warning(f"Modbus ASCII short payload on {self.port}: {decoded!r}")
            return None

        body = decoded[:-1]
        resp_lrc = decoded[-1]
        calc_lrc = self._calculate_lrc(body)
        if resp_lrc != calc_lrc:
            logger.warning(f"Modbus ASCII LRC mismatch on {self.port}")
            return None

        if len(body) >= 3 and body[1] == (function_code | 0x80):
            exception_code = body[2]
            self.error_message = (
                f"Modbus ASCII exception 0x{exception_code:02X} "
                f"for function=0x{function_code:02X}, address={address}"
            )
            logger.error(
                f"Modbus ASCII exception from ID {self.modbus_id} on {self.port}: "
                f"function=0x{function_code:02X}, exception=0x{exception_code:02X}, "
                f"address={address}"
            )
            return None

        return body

    def _send_modbus_request(self, function_code, address, value_or_count):
        if not self.serial or not self.connected:
            return None
            
        # Ensure we work with integers for modbus IDs and addresses
        modbus_id = int(self.modbus_id)
        function_code = int(function_code)
        address = int(address)
        value_or_count = int(value_or_count)

        with self.lock:
            # Modbus RTU requires a silence between packets
            time.sleep(0.05)
            self.error_message = ""

            retries = 2
            while retries >= 0:
                try:
                    self.serial.reset_input_buffer()
                    self.serial.reset_output_buffer()
                    if self.protocol == "ASCII":
                        response = self._send_ascii_request(function_code, address, value_or_count)
                    else:
                        response = self._send_rtu_request(function_code, address, value_or_count)

                    if response:
                        return response

                    # Protocol exceptions (illegal address, etc.) will not succeed on retry
                    if self.error_message and "exception" in self.error_message.lower():
                        break

                except Exception as e:
                    logger.error(f"Modbus communication error on {self.port} (FC=0x{function_code:02X}, Addr={address}): {e}")

                retries -= 1
                if retries >= 0:
                    time.sleep(0.1)

            return None

    def read_data(self):
        if not self.connected:
            return None
            
        # 1. Read PV (Temperature)
        # Use a local try-except to ensure one failure doesn't block the other
        pv_raw = None
        try:
            # Try FC 0x03 (Read Holding Register) first
            resp = self._send_modbus_request(0x03, self._wire_address(self.REG_PV), 1)
            if resp and len(resp) >= 5:
                pv_raw = struct.unpack('>h', resp[3:5])[0]
            else:
                # Fallback to FC 0x04 (Read Input Register) for PV
                logger.debug(f"Dwyer16B: FC 0x03 failed for PV at {self.REG_PV}, trying FC 0x04")
                resp = self._send_modbus_request(0x04, self._wire_address(self.REG_PV), 1)
                if resp and len(resp) >= 5:
                    pv_raw = struct.unpack('>h', resp[3:5])[0]
        except Exception as e:
            logger.debug(f"Dwyer16B: Failed to read PV: {e}")
            
        # 2. Read SV (Setpoint)
        sv_raw = None
        try:
            # Only read SV if it's a different register and we haven't failed too hard yet
            if self.REG_SV != self.REG_PV:
                resp_sv = self._send_modbus_request(0x03, self._wire_address(self.REG_SV), 1)
                if resp_sv and len(resp_sv) >= 5:
                    sv_raw = struct.unpack('>h', resp_sv[3:5])[0]
            else:
                sv_raw = pv_raw
        except Exception as e:
            logger.debug(f"Dwyer16B: Failed to read SV: {e}")
            
        # If both failed, return None to indicate a bad poll
        if pv_raw is None and sv_raw is None:
            logger.warning(f"Dwyer16B on {self.port}: Both PV and SV polls failed.")
            return None
            
        factor = 10.0 ** self.decimal_places
        data = {}
        if pv_raw is not None:
            data["Temperature"] = pv_raw / factor
        if sv_raw is not None:
            data["Setpoint"] = sv_raw / factor
            
        return data if data else None

    def run_test_action(self, action_id, input_value=None):
        if action_id == "read_snapshot":
            data = self.read_data()
            if not data:
                return {
                    "success": False,
                    "message": f"No valid response from device on {self.port}. Check ID, Baud, and A/B wiring.",
                }

            lines = [f"Read successful on {self.port}"]
            if "Temperature" in data:
                lines.append(f"PV: {data['Temperature']:.1f} °C")
            else:
                lines.append("PV: (no response)")
            if "Setpoint" in data:
                lines.append(f"SV: {data['Setpoint']:.1f} °C")
            else:
                lines.append("SV: (no response)")

            return {
                "success": True,
                "message": "\n".join(lines),
            }

        if action_id == "write_setpoint":
            if input_value in (None, ""):
                return {"success": False, "message": "No setpoint value provided."}

            target_value = float(input_value)
            success = self.write_data(f"SV={target_value}")
            if not success:
                return {
                    "success": False,
                    "message": f"Write failed on {self.port}. TXD blinked, but no response from device.",
                }

            return {
                "success": True,
                "message": f"Write command sent successfully: SV={target_value:.1f} °C",
            }

        return {"success": False, "message": f"Unknown test action: {action_id}"}

    def write_data(self, data):
        if not self.connected:
            return False
            
        try:
            command = str(data).strip().upper()
            
            if "=" in command:
                key, val_str = command.split("=", 1)
            elif " " in command:
                key, val_str = command.split(None, 1)
            else:
                return False
                
            if key in ["SV", "SET_SV", "SETPOINT"]:
                value = float(val_str)
                factor = 10.0 ** self.decimal_places
                raw_value = int(round(value * factor))
                if raw_value < -32768 or raw_value > 32767:
                    logger.error(f"SV value out of range for signed 16-bit register: {raw_value}")
                    return False

                wire_value = raw_value & 0xFFFF
                wire_sv = self._wire_address(self.REG_SV)
                logger.debug(f"Writing {raw_value} to SV register {wire_sv}")
                resp = self._send_modbus_request(0x06, wire_sv, wire_value)
                
                if resp and len(resp) >= 6:
                    logger.info(f"Successfully wrote SV={value} to {self.port}")
                    return True
                else:
                    logger.warning(f"Failed to write SV={value} to {self.port} (response: {resp!r})")
                    return False
        except Exception as e:
            logger.error(f"Error in Dwyer16B.write_data: {e}")
            
        return False
