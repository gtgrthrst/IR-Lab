# IR-Lab：Pico W 紅外線學習 / 發送

以 **Raspberry Pi Pico W + MicroPython** 做紅外線遙控器的學習與重播，
並用瀏覽器（**Web Bluetooth**）操作：按下遙控器 → 擷取波形 → 存成按鍵 → 一鍵重播。

## 硬體

| 功能 | 腳位 | 說明 |
|---|---|---|
| IR 接收 | GPIO8 | 解調型接收頭（例如 VS1838B / TSOP），閒置為高電位 |
| IR 發射 | GPIO9 | 38kHz PWM 載波，建議以電晶體驅動 IR LED |
| OLED（選配） | SDA=GPIO0、SCL=GPIO1 | SSD1306 128x64、位址 0x3C；沒接也能運作 |

腳位可在 `ir_lab.py` 開頭的 `RX_PIN`、`TX_PIN` 修改。

## 檔案結構

```
├── ir_lab.py          # Pico W 韌體：BLE 指令、擷取、重播、OLED 狀態
├── ir_lab.html        # 瀏覽器操作介面（單一 HTML，無外部相依）
├── ir_test.py         # 不需 BLE 的硬體測試：自發自收 + 監聽遙控器
├── ble_manager.py     # Nordic UART BLE 封裝（ir_lab.py 依賴）
├── ble_advertising.py # BLE 廣播 payload 輔助（ble_manager.py 依賴）
└── ssd1306.py         # SSD1306 OLED 驅動（ir_lab.py 依賴）
```

## 快速開始

### 1. 硬體測試（建議先做）

```bash
mpremote run ir_test.py
```

先讓 TX 送出一筆 NEC 並由 RX 自行解碼，接著 20 秒內監聽你的遙控器。
LED 需對準接收頭（約 30cm 內）。

### 2. 上傳韌體

```bash
mpremote cp ble_advertising.py :ble_advertising.py
mpremote cp ble_manager.py :ble_manager.py
mpremote cp ssd1306.py :ssd1306.py
mpremote run ir_lab.py          # 先試跑，不覆蓋既有 main.py
# 確認可用後，要開機自動執行：
# mpremote cp ir_lab.py :main.py + reset
```

裝置的 BLE 名稱為 `IRLab`。

### 3. 開啟網頁介面

```bash
python -m http.server 8765 --bind 127.0.0.1
```

用 Chrome / Edge 開啟 <http://localhost:8765/ir_lab.html>，按連線並選擇 `IRLab`。
`localhost` 屬於安全來源，Web Bluetooth 可正常使用。

> iOS 不支援 Web Bluetooth，請使用 [Bluefy](https://apps.apple.com/app/bluefy/id1492822055) 等瀏覽器。

## BLE 指令

走 Nordic UART 服務，指令不分大小寫：

| 指令 | 說明 | 回應 |
|---|---|---|
| `PING` | 連線測試 | `PONG` |
| `REC` | 武裝一次擷取 | `REC:ON`，收到訊框後 `IRB:<段數>`、若干 `D:<v,v,...>`、`IRE` |
| `STOP` | 取消擷取 | `REC:OFF` |
| `TEST` | 自發自收：送 NEC 並自行擷取 | 同擷取回應 |
| `SEND,<頻率>,<重複>,<v1>,<v2>,...` | 重播波形；v 單位 10µs，第一個為 mark | `SENT:<段數>` 或 `ERR:SEND` |

- 頻率範圍 20000–60000 Hz，重複 1–10 次。
- 標準 NEC 訊框會自動解碼為位址 / 指令，其他格式以原始脈衝（RAW）保存。
- 每則回應 ≤ 20 位元組，以符合預設 BLE MTU。

## 授權

本專案以 [MIT License](LICENSE) 授權。
`ssd1306.py` 與 `ble_advertising.py` 源自 MicroPython 專案範例 / 驅動（MIT），請保留其原始版權標示。
