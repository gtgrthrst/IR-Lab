"""Nordic UART BLE bridge for the power monitor.

Protocol compatible with the supplied index.html reference:
RX writes are received in chunks and terminated with END.
TX sends short text notifications so they fit the default BLE MTU.
"""

import bluetooth
from micropython import const
from ble_advertising import advertising_payload


_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
_UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), 0x08 | 0x04)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX))


class BLEManager:
    def __init__(self, name="LoraPowerSwitch"):
        self.ble = bluetooth.BLE()
        self.name = name
        self._connections = set()
        self._rx_buffer = ""
        self._pending_command = None

        self.ble.active(True)
        self.ble.irq(self._irq)
        ((self._tx_handle, self._rx_handle),) = self.ble.gatts_register_services((_UART_SERVICE,))
        self._advertise()

    def _advertise(self):
        payload = advertising_payload(name=self.name, services=[_UART_UUID])
        try:
            self.ble.gap_advertise(500_000, adv_data=payload)
        except OSError:
            pass

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._connections.add(data[0])
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._connections.discard(data[0])
            self._advertise()
        elif event == _IRQ_GATTS_WRITE and data[1] == self._rx_handle:
            try:
                chunk = self.ble.gatts_read(self._rx_handle).decode()
                if chunk == "END":
                    self._pending_command = self._rx_buffer
                    self._rx_buffer = ""
                else:
                    self._rx_buffer += chunk
            except (UnicodeError, OSError):
                self._rx_buffer = ""

    def poll_command(self):
        command = self._pending_command
        self._pending_command = None
        return command.strip().upper() if command else None

    def notify(self, message):
        data = str(message).encode()
        for conn_handle in self._connections:
            try:
                self.ble.gatts_notify(conn_handle, self._tx_handle, data)
            except OSError:
                pass

    def publish(self, relay, voltage, current, power):
        # Keep each notification short; the reference page handles text lines.
        self.notify("RELAY:" + ("ON" if relay else "OFF"))
        self.notify("VOLTAGE:" + str(round(voltage, 1)))
        self.notify("CURRENT:" + str(round(current, 3)))
        self.notify("POWER:" + str(round(power, 1)))
