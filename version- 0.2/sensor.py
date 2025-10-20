import serial
import threading
import time
import serial.tools.list_ports

class SensorReader:
    def __init__(self):
        self.data = {'temp': 0, 'humidity': 0, 'body_temp': 0, 'weight': 0, 'distance': 0, 'heart_rate': 0, 'spo2': 0}
        self.selected_port = None
        self.serial_thread = None
        self.running = False
        
    def get_available_ports(self):
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]
    
    def set_port(self, port):
        self.selected_port = port
        self.start_reading()
    
    def start_reading(self):
        if self.serial_thread and self.serial_thread.is_alive():
            self.stop_reading()
        
        self.running = True
        self.serial_thread = threading.Thread(target=self._read_serial, daemon=True)
        self.serial_thread.start()
    
    def stop_reading(self):
        self.running = False
        
    def _read_serial(self):
        if not self.selected_port:
            return
        try:
            ser = serial.Serial(self.selected_port, 115200, timeout=1)
            while self.running:
                line = ser.readline().decode().strip()
                if line.startswith("DATA_CSV:"):
                    values = line[9:].split(',')
                    if len(values) >= 7:
                        self.data['temp'] = float(values[0])
                        self.data['humidity'] = float(values[1])
                        self.data['body_temp'] = float(values[2])
                        self.data['weight'] = float(values[3])
                        self.data['distance'] = float(values[4])
                        self.data['heart_rate'] = int(float(values[5]))
                        self.data['spo2'] = int(float(values[6]))
            ser.close()
        except Exception as e:
            print(f"Serial error: {e}")
    
    def get_data(self):
        return self.data