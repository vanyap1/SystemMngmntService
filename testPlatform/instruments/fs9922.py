import threading
import time
from typing import Optional
import serial

class FS9922DMM:
    DEFAULT_BAUDRATE = 2400

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> None:
        self.port = port
        self.baudrate = baudrate
        self.serial_port: Optional[serial.Serial] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        
        # Внутрішній стан приладу, який оновлюється з порту
        self._current_value: Optional[float] = None
        self._current_unit: str = ""       # V, A, Ohm, Hz, F, C, etc.
        self._current_prefix: str = ""     # m, u, k, M або порожньо
        self._current_mode: str = ""       # AC або DC
        
        # Блокування для безпечного доступу до даних з різних потоків
        self._lock = threading.Lock()

        self._start_reading()

    def _start_reading(self) -> None:
        """Запуск фонового потоку для зчитування даних."""
        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=1)
            self.is_running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            print(f"[-] Помилка ініціалізації порту: {e}")

    def _read_loop(self) -> None:
        """Фоновий цикл збору та синхронізації пакетів."""
        buffer = bytearray()
        
        while self.is_running and self.serial_port and self.serial_port.is_open:
            try:
                data = self.serial_port.read(1)
                if not data:
                    continue
                buffer.extend(data)
                
                # Перевіряємо маркер кінця пакека (\r\n -> 0x0D 0x0A)
                if len(buffer) >= 2 and buffer[-2:] == b'\x0d\x0a':
                    if len(buffer) == 14:
                        self._parse_packet(buffer)
                    buffer.clear()
            except Exception as e:
                print(f"\n[-] Помилка зчитування з порту: {e}")
                self.is_running = False

    def _parse_packet(self, packet: bytearray) -> None:
        """Парсинг 14-байтового пакета за даташитом FS9922-DMM4."""
        try:
            # 1. Значення та знак (Байти 1-5 -> індекси 0-4)
            #print(f"\n[+] Отримано пакет: {packet.hex()}")  # Дебаг: показуємо сирий пакет
            sign = chr(packet[0])
            digits = "".join(chr(b) for b in packet[1:5])
            val = float(digits)
            if sign == '-':
                val = -val

            # 2. Позиція десяткової крапки (Реально в packet[6])
            dot_pos = packet[6]
            if dot_pos == 0x31:      # 0.000V
                val /= 1000.0
            elif dot_pos == 0x32:    # 00.00V
                val /= 1.0
            elif dot_pos == 0x34:    # 000.0mV (у даташиті помилково вказано 0x33)
                val /= 10.0
            elif dot_pos == 0x30:    # 1000V, крапки немає
                pass
            #print(f"val = {val}, dot_pos = {dot_pos:#x}")  # Дебаг: показуємо обчислене значення та позицію крапки
            # Примітка: якщо у тебе 14.40V виходить як 1440 / 100 = 14.40, 
            # то для 0x32 ділимо на 100.
            if dot_pos == 0x32:
                val /= 100

            # 3. Режим роботи AC/DC (Реально в packet[7] - SB1)
            # Bit4 (0x10) = DC, Bit3 (0x08) = AC
            sb1 = packet[7]
            if sb1 & 0x10:
                mode = "DC"
            elif sb1 & 0x08:
                mode = "AC"
            else:
                mode = ""
            #print(f"Режим: {mode}, SB1: {sb1:#x}")  # Дебаг: показуємо режим та байт SB1
            # 4. Множники / Префікси (Реально в packet[9] - SB3)
            sb3 = packet[9]
            prefix = ""
            if sb3 & 0x40:   prefix = "m"
            elif sb3 & 0x80: prefix = "u"
            elif sb3 & 0x20: prefix = "k"
            elif sb3 & 0x10: prefix = "M"
            #print(f"Префікс: {prefix}, SB3: {sb3:#x}")  # Дебаг: показуємо префікс та байт SB3
            # 5. Одиниці виміру (Реально в packet[10] - SB4)
            sb4 = packet[10]
            unit = "Unknown"
            
            if sb4 & 0x80:   unit = "V"     # Твій випадок, біт 0x80 активний!
            elif sb4 & 0x40: unit = "A"     
            elif sb4 & 0x20: unit = "Ohm"   
            elif sb4 & 0x10: unit = "hFE"   
            elif sb4 & 0x08: unit = "Hz"    
            elif sb4 & 0x04: unit = "F"     
            elif sb4 & 0x02: unit = "C"     
            elif sb4 & 0x01: unit = "Fahrenheit" 
            #print(f"Одиниця: {unit}, SB4: {sb4:#x}")  # Дебаг: показуємо одиницю та байт SB4
            # Додаткова перевірка на Beep в SB3 (packet[9])
            if sb3 & 0x08:
                unit = "Beep"
            #print(f"{val} {prefix}{unit} ({mode})")  # Виводимо результат у консоль для дебагу
            # Синхронно оновлюємо стан об'єкта
            with self._lock:
                self._current_value = val
                self._current_unit = unit
                self._current_prefix = prefix
                self._current_mode = mode
                
        except (ValueError, IndexError):
            pass  # Ігноруємо біті пакети

    # --- Публічні методи для отримання даних у базових величинах ---

    def getVolt(self) -> Optional[float]:
        """Повертає поточну напругу в Вольтах."""
        with self._lock:
            if self._current_unit == "V":
                return self._scale_to_base(self._current_value, self._current_prefix)
        return None

    def getAmp(self) -> Optional[float]:
        """Повертає поточний струм в Амперах."""
        with self._lock:
            if self._current_unit == "A":
                return self._scale_to_base(self._current_value, self._current_prefix)
        return None

    def getOhm(self) -> Optional[float]:
        """Повертає опір в Омах."""
        with self._lock:
            if self._current_unit == "Ohm":
                return self._scale_to_base(self._current_value, self._current_prefix)
        return None

    def getHz(self) -> Optional[float]:
        """Повертає частоту в Герцах."""
        with self._lock:
            if self._current_unit == "Hz":
                return self._scale_to_base(self._current_value, self._current_prefix)
        return None

    def getFarad(self) -> Optional[float]:
        """Повертає ємність в Фарадах."""
        with self._lock:
            if self._current_unit == "F":
                return self._scale_to_base(self._current_value, self._current_prefix)
        return None

    def getTemp(self) -> Optional[float]:
        """Повертає температуру в градусах Цельсія."""
        with self._lock:
            if self._current_unit == "C":
                return self._current_value
        return None

    def get_raw_string(self) -> str:
        """Повертає зліпок поточного стану (наприклад: 'DC 14.46 V')."""
        with self._lock:
            if self._current_value is None:
                return "Немає даних від мультиметра..."
            return f"{self._current_mode} {self._current_value} {self._current_prefix}{self._current_unit}"

    def _scale_to_base(self, value: Optional[float], prefix: str) -> Optional[float]:
        """Множник для переведення мілі/мікро/кіло до базової одиниці."""
        if value is None:
            return None
        scale = {"u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}
        return value * scale.get(prefix, 1.0)

    def close(self) -> None:
        """Закриття порту та зупинка фонового потоку."""
        self.is_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()


# --- Командний процесор ---

if __name__ == '__main__':
    # Шлях до FTDI пристрою на твоєму NanoPi
    port_path = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AL058YDQ-if00-port0"
    
    print(f"[+] Підключення до мультиметра на {port_path}...")
    dmm = FS9922DMM(port=port_path)
    
    # Чекаємо 1 секунду на перші пакети
    time.sleep(1)
    
    if not dmm.is_running:
        print("[-] Не вдалося запустити зчитування. Перевір лінію.")
        exit(1)

    print("\nДоступні команди:")
    print("  v - Отримати напругу (V)")
    print("  a - Отримати струм (A)")
    print("  r - Отримати опір (Ohm)")
    print("  f - Отримати частоту (Hz)")
    print("  s - Показати екран повністю (стан + одиниці виміру)")
    print("  q - Вихід")
    print("-" * 40)

    try:
        while True:
            cmd = input("Введіть команду > ").strip().lower()
            
            if cmd == 'v':
                volt = dmm.getVolt()
                print(f"Напруга: {volt} V" if volt is not None else "Прилад не в режимі вимірювання напруги.")
            
            elif cmd == 'a':
                amp = dmm.getAmp()
                print(f"Струм: {amp} A" if amp is not None else "Прилад не в режимі вимірювання струму.")
                
            elif cmd == 'r':
                ohm = dmm.getOhm()
                print(f"Опір: {ohm} Ohm" if ohm is not None else "Прилад не в режимі вимірювання опору.")
                
            elif cmd == 'f':
                hz = dmm.getHz()
                print(f"Частота: {hz} Hz" if hz is not None else "Прилад не в режимі вимірювання частоти.")

            elif cmd == 's':
                print(f"Поточний стан: {dmm.get_raw_string()}")
                
            elif cmd == 'q':
                print("[+] Завершення роботи...")
                break
            elif cmd == '':
                continue
            else:
                print("Невідома команда. Спробуй v, a, r, f, s або q.")
                
    except KeyboardInterrupt:
        print("\n[+] Примусове завершення...")
    finally:
        dmm.close()