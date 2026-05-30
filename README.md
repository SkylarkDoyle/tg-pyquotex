# 🚀 PyQuotex

---
<p align="center">
  <a href="https://github.com/cleitonleonel/pyquotex">
    <img src="pyquotex.png" alt="pyquotex" width="45%" height="auto">
  </a>
</p>
<p align="center">
  <i>Unofficial Quotex Library API Client written in Python!</i>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-green" alt="Python Versions"/>
</p>

---

## 📘 Sobre o projeto (PT-BR)

O **PyQuotex** nasceu como uma biblioteca open-source para facilitar a comunicação com a plataforma Quotex via WebSockets. Com o tempo e devido ao uso indevido, uma versão privada mais segura e robusta foi criada.

---

## 📘 About the Project (EN)

**PyQuotex** started as an open-source library to make it easier to communicate with the Quotex platform using WebSockets. Due to misuse, a more robust private version was later introduced.

---

## 🎯 Objetivo da Biblioteca / Library Goal

Prover ferramentas para desenvolvedores integrarem seus sistemas com a plataforma Quotex, permitindo operações automatizadas de forma segura e eficiente.

> ⚠️ Esta biblioteca **não é um robô de operações** e não toma decisões por conta própria.

---

# 📚 Documentação Completa
https://cleitonleonel.github.io/pyquotex/


## 🛠 Instalação

### 1. Clone o repositório:

```bash
git clone https://github.com/cleitonleonel/pyquotex.git
cd pyquotex
poetry install
poetry run python app.py
```

### 2. Ou instale diretamente no seu projeto com Poetry:

```bash
poetry add git+https://github.com/cleitonleonel/pyquotex.git
```

### 2.1. Instale com um comando no Termux (Android):

```shell
curl -sSL https://raw.githubusercontent.com/cleitonleonel/pyquotex/refs/heads/master/run_in_termux.sh | sh
```

### 3. Requisitos adicionais
Se você encontrar um erro relacionado ao `playwright install` ao usar esta biblioteca, siga os passos abaixo para resolver o problema.

### Instalar navegadores do Playwright
Certifique-se de que o Playwright e os navegadores compatíveis estejam instalados.

![playwright_info.png](playwright_info.png)

```bash
playwright install
```
---

## 🧪 Exemplo de uso

```python
from pyquotex.stable_api import Quotex

client = Quotex(
  email="your_email",
  password="your_password",
  lang="pt"  # ou "en"
)

await client.connect()
print(await client.get_balance())
await client.close()
```

---

## 💡 Recursos Principais

| Função                     | Descrição                              |
| -------------------------- | -------------------------------------- |
| `connect()`                | Conecta via WebSocket com reconexão    |
| `get_balance()`            | Retorna o saldo da conta               |
| `buy_simple()`             | Realiza uma operação de compra simples |
| `buy_and_check_win()`      | Compra e verifica o resultado          |
| `get_candle()`             | Retorna candles históricos             |
| `get_realtime_sentiment()` | Sentimento em tempo real do ativo      |
| `balance_refill()`         | Recarrega a conta demo                 |

---

## 🔒 Versão Privada Disponível

Uma versão privada está disponível com recursos adicionais, estabilidade aprimorada e melhor suporte.

👉 [Acesse a versão privada](https://t.me/pyquotex/852) para desbloquear o máximo do PyQuotex!

### 💥 Comparativo de Versões

| Recurso                        | Open Source ✅ | Versão Privada ✨      |
|--------------------------------| ------------- | --------------------- |
| Suporte a Multilogin           | ❌             | ✅                     |
| Monitoramento de Sentimentos   | ✅             | ✅ + detecção avançada |
| Proxy/DNS Customizado          | ❌             | ✅                     |
| Robustez e Alta Confiabilidade | ✅             | ✨ Nível enterprise    |
| Velocidade de Execução         | ✅             | ⚡ Ultra rápido        |
| Suporte                        | ❌             | ✅                     |

---

## 🤝 Apoie este projeto

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/cleiton.leonel)

### 💸 Criptomoedas

* **Dogecoin (DOGE)**: `DMwSPQMk61hq49ChmTMkgyvUGZbVbWZekJ`
* **Bitcoin (BTC)**: `bc1qtea29xkpyx9jxtp2kc74m83rwh93vjp7nhpgkm`
* **Ethereum (ETH)**: `0x20d1AD19277CaFddeE4B8f276ae9f3E761523223`
* **Solana (SOL)**: `4wbE2FVU9x4gVErVSsWwhcdXQnDBrBVQFvbMqaaykcqo`

---

## 🤖 Telegram Signals Bot

The `examples/telegram_signals_bot.py` script monitors a Telegram channel for trading signals and automatically executes trades on Quotex. It features a **Sniper Entry** system that waits for a better price before executing, instead of entering at market price immediately.

### How It Works

1. A signal provider posts a message in the Telegram channel (e.g. `USD CAD OTC ✅ Wait FOR DIRECTION`)
2. The bot parses the asset pair and waits for a direction sticker/message (`UP`/`CALL` or `DOWN`/`PUT`)
3. When a direction is detected, the **Sniper Entry** system activates:
   - Fetches the close price of the last completed 1-minute candle as a baseline
   - For **CALL**: waits up to 20 seconds for the price to **dip** below the baseline
   - For **PUT**: waits up to 20 seconds for the price to **spike** above the baseline
   - If no better entry is found within the window, the trade is **skipped**
4. If triggered, the trade is placed on Quotex with the configured amount and duration

### Prerequisites

| Requirement | Details |
|---|---|
| **Python** | 3.12 or 3.13 |
| **Playwright** | `playwright install chromium` (Chrome must be installed on your system) |
| **Telegram Account** | A personal Telegram account (not a bot token) |
| **Telegram API Keys** | Obtained from [my.telegram.org](https://my.telegram.org) |
| **Quotex Account** | A Quotex account with email/password login |

### Step 1: Install Dependencies

```bash
git clone https://github.com/cleitonleonel/pyquotex.git
cd pyquotex
pip install -r requirements.txt
playwright install chromium
```

Or with Poetry:

```bash
poetry install
poetry run playwright install chromium
```

### Step 2: Get Telegram API Credentials

1. Go to [https://my.telegram.org/auth](https://my.telegram.org/auth)
2. Log in with your phone number
3. Click **"API development tools"**
4. Fill in any app title and short name
5. Copy your **`api_id`** (integer) and **`api_hash`** (string)

### Step 3: Get the Telegram Channel ID

To find the channel ID you want to monitor:

1. Open Telegram Web ([https://web.telegram.org](https://web.telegram.org))
2. Navigate to the channel
3. The URL will look like `https://web.telegram.org/a/#-1001234567890`
4. The number after `#` is your channel ID (include the `-100` prefix)

Alternatively, forward a message from the channel to [@userinfobot](https://t.me/userinfobot) on Telegram.

### Step 4: Configure `settings/config.ini`

Edit the file `settings/config.ini` in the project root:

```ini
[settings]
email=your_quotex_email@example.com
password=your_quotex_password

[telegram]
api_id=12345678
api_hash=your_api_hash_string_here
channel=-1001234567890

[trading]
amount=1
duration=60
account_mode=PRACTICE
```

| Key | Description |
|---|---|
| `email` / `password` | Your Quotex login credentials |
| `api_id` / `api_hash` | From [my.telegram.org](https://my.telegram.org) |
| `channel` | Telegram channel ID to monitor (negative integer) |
| `amount` | Trade amount in USD (e.g. `1`, `2`, `5`) |
| `duration` | Default trade duration in seconds (e.g. `60` = 1 minute) |
| `account_mode` | `PRACTICE` (demo) or `REAL` (live money — **use with caution**) |

### Step 5: Run the Bot

Run from the **project root directory** (not from inside `examples/`):

```bash
python -m examples.telegram_signals_bot
```

Or with a virtual environment:

```bash
.venv/Scripts/python -m examples.telegram_signals_bot    # Windows
.venv/bin/python -m examples.telegram_signals_bot         # Linux/macOS
```

**Headless mode** (for VPS / servers without a display):

```bash
python -m examples.telegram_signals_bot --headless
```

> ⚠️ **Important:** Use `-m examples.telegram_signals_bot` (module syntax), **not** `python examples/telegram_signals_bot.py`. The module syntax ensures Python can resolve the `pyquotex` package imports correctly.

### First Run

On the first run, two things will happen:

1. **Telegram login** — You will be prompted in the terminal to enter your phone number and a verification code sent to your Telegram app. This creates a `settings/telegram_session.session` file so you won't need to log in again.

2. **Quotex browser login** — A Chrome window will open and navigate to Quotex. If you haven't logged in before, enter your credentials. Complete any CAPTCHA or 2FA prompts. The session is saved in `settings/browser_data/` so subsequent runs log in automatically.

### Expected Output

```
2026-05-30 19:47:31 [INFO] ============================================================
2026-05-30 19:47:31 [INFO] 🤖 Telegram Signals Bot for PyQuotex
2026-05-30 19:47:31 [INFO] ============================================================
2026-05-30 19:47:31 [INFO] Launching Chrome (browser stays open for WebSocket)...
2026-05-30 19:47:33 [INFO] Already logged in from previous session!
2026-05-30 19:47:36 [INFO] Browser logged in. Token: GLLMCVXTZo...
2026-05-30 19:47:38 [INFO] Connected to Telegram
2026-05-30 19:47:38 [INFO] Monitoring channel: Test Chat
2026-05-30 19:47:38 [INFO] ============================================================
2026-05-30 19:47:38 [INFO] Bot is running. Listening for signals...
2026-05-30 19:47:38 [INFO]    Account: PRACTICE | Amount: $2.00 | Default Duration: 60s
2026-05-30 19:47:38 [INFO]    Press Ctrl+C to stop.
2026-05-30 19:47:38 [INFO] ============================================================
```

When a signal is received and executed:

```
[INFO] New signal parsed: PendingSignal(asset=USDCAD, duration=60s)
[INFO] Waiting for direction sticker/message...
[INFO] Direction detected: PUT for pending signal PendingSignal(asset=USDCAD, duration=60s)
[INFO] Sniper mode: Waiting up to 20s for a better PUT entry...
[INFO] Found exact signal reference candle (Time: 1780167060) close price: 1.36685
[INFO] Sniper baseline (True Open): 1.36685 | Target: 1.36692
[INFO] Sniper PUT triggered! Price spiked to 1.36704
[INFO] Trade placed! Asset: USDCAD_otc | Direction: PUT | Amount: $2.00 | Duration: 60s
```

### Stopping the Bot

Press `Ctrl+C` in the terminal. The bot will gracefully disconnect from both Telegram and Quotex.

### Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError: No module named 'pyquotex'` | Run with `-m` flag from the project root: `python -m examples.telegram_signals_bot` |
| `ModuleNotFoundError: No module named 'telethon'` | Install dependencies: `pip install telethon` |
| Telegram asks for login every time | Check that `settings/telegram_session.session` file exists and is not deleted between runs |
| Quotex trades stop executing after hours | The bot has built-in browser keep-alive and supervisor loops to prevent this. Restart if it persists. |
| `Sniper window expired. Skipping trade.` | Normal behavior — the Sniper system didn't find a favorable entry within 20 seconds |
| Browser CAPTCHA on every run | Use a persistent browser profile by keeping `settings/browser_data/` intact |

---

## 📞 Contato

* Telegram: [@cleitonleonel](https://t.me/cleitonleonel)
* GitHub: [cleitonleonel](https://github.com/cleitonleonel)
* LinkedIn: [Cleiton Leonel](https://www.linkedin.com/in/cleiton-leonel-creton-331138167/)

---
