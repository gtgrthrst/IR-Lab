"""IR learn/replay firmware (Pico W) driven by ir_lab.html over BLE.

RX = GPIO8 (demodulated receiver, idle high), TX = GPIO9 (38kHz PWM carrier).
Standalone: does not touch main.py. Run with `mpremote run ir_lab.py`
or copy to the device as main.py when needed.

BLE (Nordic UART via ble_manager.BLEManager), commands are upper-cased:
  PING                       -> PONG
  REC                        arm one capture   -> REC:ON ... IRB:n, D:.., IRE
  STOP                       disarm            -> REC:OFF
  SEND,freq,repeat,v1,v2,..  v = mark/space lengths in 10us, mark first
                                               -> SENT:n or ERR:SEND
Capture result: IRB:<count>, then D:<v,v,..> lines (<=20 bytes), then IRE.
"""
from machine import Pin, PWM, I2C
from array import array
import time
from ble_manager import BLEManager
import ssd1306

RX_PIN, TX_PIN = 8, 9
MAX_EDGES = 400
END_GAP_US = 60_000  # silence that closes a frame
DUTY = 21845  # ~33% carrier duty

try:
    oled = ssd1306.SSD1306_I2C(128, 64, I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000), addr=0x3C)
except OSError:
    oled = None  # run without a display
ble = BLEManager("IRLab")
rx = Pin(RX_PIN, Pin.IN)
pwm = PWM(Pin(TX_PIN), freq=38000, duty_u16=0)

stamps = array("I", [0] * MAX_EDGES)
count = 0
armed = False
rx_total = tx_total = 0
rx_info = ("-", "")  # (protocol, code) of the last capture
tx_info = "-"
dirty = True


def notify(msg):
    """Like BLEManager.notify but retries when the BLE queue is full instead of silently dropping."""
    data = msg.encode()
    for handle_ in list(ble._connections):
        for _ in range(40):
            try:
                ble.ble.gatts_notify(handle_, ble._tx_handle, data)
                break
            except OSError:
                time.sleep_ms(10)


def _irq(pin):
    global count
    if count < MAX_EDGES:
        stamps[count] = time.ticks_us()
        count += 1


def arm():
    global count, armed, dirty
    dirty = True
    count = 0
    armed = True
    rx.irq(_irq, Pin.IRQ_FALLING | Pin.IRQ_RISING)
    notify("REC:ON")


def disarm(announce=True):
    global armed, dirty
    dirty = True
    armed = False
    rx.irq(handler=None)
    if announce:
        notify("REC:OFF")


def nec_decode(units):
    """units in 10us; returns (addr, cmd) for a standard NEC frame else None."""
    if len(units) < 66 or not 630 < units[0] < 1170 or not 315 < units[1] < 585:
        return None
    v = 0
    for i in range(32):
        if units[3 + 2 * i] > 110:
            v |= 1 << i
    a, ia, c, ic = v & 255, (v >> 8) & 255, (v >> 16) & 255, v >> 24
    return (a, c) if a ^ ia == 255 and c ^ ic == 255 else None


def show():
    global dirty
    dirty = False
    if not oled:
        return
    oled.fill(0)
    oled.text("IR Lab", 0, 0)
    oled.text("BLE:" + ("ON" if ble._connections else "--"), 64, 0)
    oled.text("RX:G%d TX:G%d" % (RX_PIN, TX_PIN), 0, 12)
    oled.text("REC " + ("waiting" if armed else "idle"), 0, 24)
    oled.text("RX#%d %s" % (rx_total, rx_info[0]), 0, 36)
    oled.text(rx_info[1], 0, 46)
    oled.text("TX#%d %s" % (tx_total, tx_info), 0, 56)
    oled.show()


def report():
    n = count
    units = []
    for i in range(n - 1):
        units.append((time.ticks_diff(stamps[i + 1], stamps[i]) + 5) // 10)
    global rx_total, rx_info, dirty
    rx_total += 1
    nec = nec_decode(units)
    rx_info = ("NEC", "A=%02X C=%02X" % nec) if nec else ("RAW", "%d pulses" % len(units))
    dirty = True
    notify("IRB:" + str(len(units)))
    line = "D:"
    for v in units:
        item = str(v) + ","
        if len(line) + len(item) > 20:
            notify(line)
            time.sleep_ms(25)
            line = "D:"
        line += item
    if len(line) > 2:
        notify(line)
        time.sleep_ms(25)
    notify("IRE")


def send(freq, repeat, units):
    global tx_total, tx_info, dirty
    tx_total += 1
    tx_info = "%dx%d" % (len(units), repeat)
    dirty = True
    was_armed = armed
    if was_armed:
        rx.irq(handler=None)
    pwm.freq(freq)
    for r in range(repeat):
        deadline = time.ticks_us()
        for i, v in enumerate(units):
            pwm.duty_u16(DUTY if i % 2 == 0 else 0)
            deadline = time.ticks_add(deadline, v * 10)
            while time.ticks_diff(deadline, time.ticks_us()) > 0:
                pass
        pwm.duty_u16(0)
        if r < repeat - 1:
            time.sleep_ms(40)
    if was_armed:
        arm_irq_only()


def arm_irq_only():
    global count
    count = 0
    rx.irq(_irq, Pin.IRQ_FALLING | Pin.IRQ_RISING)


NEC_TEST = [900, 450]
for _i in range(32):
    NEC_TEST += [56, 169 if (0xBA45FF00 >> _i) & 1 else 56]
NEC_TEST.append(56)


def handle(cmd):
    if cmd == "PING":
        notify("PONG")
    elif cmd == "REC":
        arm()
    elif cmd == "STOP":
        disarm()
    elif cmd == "TEST":  # loopback: send a NEC frame and capture it ourselves
        arm_irq_only()
        send(38000, 1, NEC_TEST)
        time.sleep_ms(80)
        disarm(False)
        report()
    elif cmd.startswith("SEND,"):
        try:
            p = cmd.split(",")
            freq, repeat = int(p[1]), int(p[2])
            units = [int(x) for x in p[3:] if x]
            if not 20000 <= freq <= 60000 or not 1 <= repeat <= 10 or len(units) < 2:
                raise ValueError
            send(freq, repeat, units)
            notify("SENT:" + str(len(units)))
        except (ValueError, IndexError):
            notify("ERR:SEND")


print("IRLab ready: RX GPIO%d TX GPIO%d" % (RX_PIN, TX_PIN))
last_conn = None
while True:
    conn = bool(ble._connections)
    if conn != last_conn:
        last_conn = conn
        dirty = True
    if dirty:
        show()
    cmd = ble.poll_command()
    if cmd:
        handle(cmd)
    if armed and count and time.ticks_diff(time.ticks_us(), stamps[count - 1]) > END_GAP_US:
        if count >= 4:
            disarm(False)
            report()
        else:
            count = 0  # drop noise glitches
    time.sleep_ms(5)
