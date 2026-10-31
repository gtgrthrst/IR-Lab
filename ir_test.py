"""IR 測試：RX=GPIO8（解調型接收頭，閒置高電位）、TX=GPIO9（38kHz 載波）
用法：mpremote run ir_test.py   （不要覆蓋 main.py）
流程：1) 自發自收測試（TX 送 NEC，RX 解碼比對）  2) 持續監聽遙控器
"""
from machine import Pin, PWM
import time

RX_PIN, TX_PIN = 8, 9
rx = Pin(RX_PIN, Pin.IN)
tx = PWM(Pin(TX_PIN), freq=38000, duty_u16=0)

edges = []
last = 0


def _irq(p):
    global last
    now = time.ticks_us()
    if len(edges) < 140:
        edges.append((time.ticks_diff(now, last), p.value()))
    last = now


def mark(us):
    tx.duty_u16(21845)  # ~33% duty
    time.sleep_us(us)
    tx.duty_u16(0)


def send_nec(addr, cmd):
    data = addr | ((addr ^ 0xFF) << 8) | (cmd << 16) | ((cmd ^ 0xFF) << 24)
    mark(9000); time.sleep_us(4500)
    for i in range(32):
        mark(560)
        time.sleep_us(1690 if (data >> i) & 1 else 560)
    mark(560)


def decode_nec(ev):
    """ev: [(間隔us, 邊緣後電位)]；解調輸出 低=有載波。回傳 (addr, cmd) 或 None"""
    # 取各「低電位」(mark) 與其後「高電位」(space) 的長度
    spaces = []
    for i in range(1, len(ev)):
        if ev[i][1] == 1:  # 上升沿：前一段為 mark，此間隔=mark 長
            continue
        spaces.append(ev[i][0])  # 下降沿：此間隔=前一段 space 長
    # spaces[0] 為閒置時間，spaces[1] 為 4.5ms 引導 space，之後 32 個資料 space
    k = next((i for i, x in enumerate(spaces) if 3500 < x < 5500), None)
    if k is None:
        return None
    s = spaces[k:]
    if len(s) < 33:
        return None
    v = 0
    for i, x in enumerate(s[1:33]):
        if x > 1100:
            v |= 1 << i
    a, ia, c, ic = v & 255, (v >> 8) & 255, (v >> 16) & 255, v >> 24
    if a ^ ia == 255 and c ^ ic == 255:
        return a, c
    return None


def capture(wait_ms):
    global last
    edges.clear()
    last = time.ticks_us()
    rx.irq(_irq, Pin.IRQ_FALLING | Pin.IRQ_RISING)
    t0 = time.ticks_ms()
    quiet = 0
    n = 0
    while time.ticks_diff(time.ticks_ms(), t0) < wait_ms:
        time.sleep_ms(20)
        if len(edges) and len(edges) == n:
            quiet += 1
            if quiet >= 3:
                break
        else:
            quiet = 0
        n = len(edges)
    rx.irq(handler=None)
    return list(edges)


print("RX idle level GPIO%d = %d (解調接收頭應為 1)" % (RX_PIN, rx.value()))

print("\n[1] 自發自收：TX 送 NEC addr=0x00 cmd=0x45")
ok = 0
for n in range(3):
    edges.clear()
    last = time.ticks_us()
    rx.irq(_irq, Pin.IRQ_FALLING | Pin.IRQ_RISING)
    send_nec(0x00, 0x45)
    time.sleep_ms(50)
    rx.irq(handler=None)
    ev = list(edges)
    r = decode_nec(ev)
    print("  第%d次：邊緣=%d 解碼=%s" % (n + 1, len(ev), r))
    if r is None:
        print("   spaces:", [x[0] for x in ev if x[1] == 0])
    if r == (0x00, 0x45):
        ok += 1
    time.sleep_ms(300)
if ok:
    print("  => TX/RX 迴路 PASS (%d/3)" % ok)
else:
    print("  => 迴路未通：LED 需對準接收頭 (<30cm)，或檢查 GPIO9 驅動電晶體/LED 極性")

print("\n[2] 監聽遙控器 20 秒，請對 GPIO8 接收頭按遙控器…")
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < 20000:
    ev = capture(500)
    if len(ev) > 10:
        print("  收到 %d 邊緣，NEC=%s" % (len(ev), decode_nec(ev)))
print("結束")
tx.deinit()
