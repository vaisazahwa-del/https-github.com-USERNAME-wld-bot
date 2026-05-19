import os
import sys
import json
import time
import threading
import urllib.request
import urllib.error
from web3 import Web3

# Konfigurasi
RPC_URL = "https://worldchain-mainnet.g.alchemy.com/public"
WLD_CONTRACT_ADDRESS = "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
USERNAMES_API = "https://usernames.worldcoin.org/api/v1"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LAST_BLOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_block.txt")
PROCESSED_TX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_tx.txt")

# Dev wallet untuk tracking saldo
DEV_ADDRESS = "0x81c7434f9F2a4BbD4616aEc36c8f7ae498fEea86"

# Telegram
TELEGRAM_BOT_TOKEN = "8960932344:AAFhBW0h7KFtB2u_VmzyhLDl-HwgFl9WXAA"
TELEGRAM_CHAT_ID = "1232145568"

# ERC20 Transfer event signature
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# Interval polling (detik)
POLL_INTERVAL = 15

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    }
]

# Allowed chat IDs
ALLOWED_CHAT_IDS = ["1232145568", "-1003933997757", "-1002280793295"]

# Lock untuk file operations
wallets_lock = threading.Lock()


# ============ DATA PER CHAT ============

def get_wallets_file(chat_id):
    """Get wallets file path per chat ID."""
    os.makedirs(DATA_DIR, exist_ok=True)
    safe_id = str(chat_id).replace("-", "neg")
    return os.path.join(DATA_DIR, f"wallets_{safe_id}.txt")


def load_wallets_for_chat(chat_id):
    """Load wallets untuk chat tertentu."""
    filepath = get_wallets_file(chat_id)
    result = {}
    if not os.path.exists(filepath):
        return result
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            address = parts[0].lower()
            label = parts[1] if len(parts) > 1 else address[:10]
            result[address] = label
    return result


def load_all_wallets():
    """Load semua wallets dari semua chat (untuk tracker)."""
    # Return dict: address -> list of (chat_id, label)
    all_wallets = {}
    os.makedirs(DATA_DIR, exist_ok=True)

    for filename in os.listdir(DATA_DIR):
        if not filename.startswith("wallets_") or not filename.endswith(".txt"):
            continue

        # Extract chat_id dari filename
        chat_id = filename.replace("wallets_", "").replace(".txt", "").replace("neg", "-")
        filepath = os.path.join(DATA_DIR, filename)

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(None, 1)
                address = parts[0].lower()
                label = parts[1] if len(parts) > 1 else address[:10]

                if address not in all_wallets:
                    all_wallets[address] = []
                all_wallets[address].append({'chat_id': chat_id, 'label': label})

    return all_wallets


def save_wallet_for_chat(chat_id, address, username):
    """Simpan wallet untuk chat tertentu."""
    with wallets_lock:
        existing = load_wallets_for_chat(chat_id)
        if address.lower() not in existing:
            filepath = get_wallets_file(chat_id)
            with open(filepath, 'a') as f:
                f.write(f"{address} {username}\n")
            return True
        return False


def remove_wallet_for_chat(chat_id, username):
    """Hapus wallet dari chat tertentu."""
    with wallets_lock:
        existing = load_wallets_for_chat(chat_id)
        found = None
        for addr, label in existing.items():
            if label.lower() == username.lower():
                found = addr
                break

        if not found:
            return False

        filepath = get_wallets_file(chat_id)
        lines = []
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith('#') or not stripped:
                        lines.append(line)
                        continue
                    parts = stripped.split(None, 1)
                    if parts[0].lower() != found:
                        lines.append(line)

        with open(filepath, 'w') as f:
            f.writelines(lines)

        return True


# ============ TELEGRAM BOT ============

def send_telegram(message, chat_id=None, reply_markup=None):
    """Kirim pesan ke Telegram. Return message_id."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id or TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        return data.get('result', {}).get('message_id')
    except Exception as e:
        print(f"[ERROR] Telegram send: {e}")
        return None


def delete_telegram_message(chat_id, message_id):
    """Hapus pesan Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    """Edit pesan Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram edit: {e}")
        return False


def answer_callback(callback_id, text=""):
    """Answer callback query."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def get_updates(offset=None):
    """Get updates dari Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=30"
    if offset:
        url += f"&offset={offset}"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=35)
        data = json.loads(resp.read().decode())
        return data.get('result', [])
    except Exception:
        return []


def resolve_username(username):
    """Resolve username ke wallet address."""
    username = username.strip().lstrip('@')
    try:
        url = f"{USERNAMES_API}/{username}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        return data.get('address')
    except Exception:
        return None


def get_balance(contract, address, decimals):
    """Get WLD balance."""
    try:
        checksum = Web3.to_checksum_address(address)
        raw = contract.functions.balanceOf(checksum).call()
        return raw / (10 ** decimals)
    except Exception:
        return None


def get_last_block():
    """Baca last block yang sudah di-scan."""
    if os.path.exists(LAST_BLOCK_FILE):
        with open(LAST_BLOCK_FILE, 'r') as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return None
    return None


def save_last_block(block_num):
    """Simpan last block."""
    with open(LAST_BLOCK_FILE, 'w') as f:
        f.write(str(block_num))


def load_processed_tx():
    """Load processed TX hashes from file."""
    processed = set()
    if os.path.exists(PROCESSED_TX_FILE):
        with open(PROCESSED_TX_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    processed.add(line)
    return processed


def save_processed_tx(tx_hash):
    """Add new TX hash to processed file."""
    with open(PROCESSED_TX_FILE, 'a') as f:
        f.write(f"{tx_hash}\n")


# ============ TELEGRAM COMMAND HANDLER ============

def handle_command(chat_id, text, w3, contract, decimals, symbol):
    """Handle command dari Telegram."""
    if chat_id not in ALLOWED_CHAT_IDS:
        send_telegram("⛔ Akses ditolak.", chat_id)
        return

    parts = text.strip().split()
    cmd = parts[0].lower().split('@')[0]  # Handle /cmd@botname format

    if cmd == '/start' or cmd == '/help':
        msg = (
            "<b>WLD Tracker Bot</b>\n\n"
            "Commands:\n"
            "/add &lt;username/address&gt; [label] - Tambah untuk tracking\n"
            "/remove &lt;username/label&gt; - Hapus dari tracking\n"
            "/list - Lihat semua wallet yang di-track\n"
            "/balance &lt;username&gt; - Cek balance username\n"
            "/balanceall - Cek balance semua wallet\n"
            "/dev - Cek saldo dev wallet (WLD + ETH)\n"
            "/est - Estimasi saldo dev habis kapan\n"
            "/help - Tampilkan bantuan ini\n\n"
            "<i>Setiap grup punya database terpisah.</i>"
        )
        send_telegram(msg, chat_id)

    elif cmd == '/add':
        if len(parts) < 2:
            send_telegram("Format: /add &lt;username&gt; [username2] [username3]\nContoh: /add tim24.6840 user2.123", chat_id)
            return

        inputs = [p.strip().lstrip('@') for p in parts[1:]]

        # Kirim pesan processing
        processing_msg_id = send_telegram(f"⏳ Resolving {len(inputs)} username...", chat_id)

        results = []
        for input_val in inputs:
            if input_val.startswith('0x') and len(input_val) == 42:
                added = save_wallet_for_chat(chat_id, input_val, input_val[:10])
                if added:
                    results.append(f"✅ {input_val[:10]} Add")
                else:
                    results.append(f"⚠️ {input_val[:10]} sudah ada")
            else:
                address = resolve_username(input_val)
                if not address:
                    results.append(f"❌ {input_val} tidak ditemukan")
                    continue
                added = save_wallet_for_chat(chat_id, address, input_val)
                if added:
                    results.append(f"✅ {input_val} Add")
                else:
                    results.append(f"⚠️ {input_val} sudah ada")

        # Hapus pesan processing, tampilkan hasil
        if processing_msg_id:
            delete_telegram_message(chat_id, processing_msg_id)
        msg = "\n".join(results)
        send_telegram(msg, chat_id)

    elif cmd == '/remove':
        if len(parts) < 2:
            send_telegram("Format: /remove &lt;username&gt; [username2] [username3]\nContoh: /remove tim24.6840 user2.123", chat_id)
            return

        inputs = [p.strip().lstrip('@') for p in parts[1:]]

        # Kirim pesan processing
        processing_msg_id = send_telegram(f"⏳ Removing {len(inputs)} username...", chat_id)

        results = []
        for username in inputs:
            removed = remove_wallet_for_chat(chat_id, username)
            if removed:
                results.append(f"✅ {username} Removed")
            else:
                results.append(f"❌ {username} tidak ditemukan")

        # Hapus pesan processing, tampilkan hasil
        if processing_msg_id:
            delete_telegram_message(chat_id, processing_msg_id)
        msg = "\n".join(results)
        send_telegram(msg, chat_id)

    elif cmd == '/list':
        current = load_wallets_for_chat(chat_id)

        if not current:
            send_telegram("Daftar tracking kosong.", chat_id)
            return

        msg = f"<b>Wallet Tracking ({len(current)}):</b>\n\n"
        for idx, (addr, label) in enumerate(current.items(), 1):
            msg += f"{idx}. <b>{label}</b>\n   <code>{addr}</code>\n"

        send_telegram(msg, chat_id)

    elif cmd == '/balance':
        if len(parts) < 2:
            send_telegram("Format: /balance &lt;username&gt;\nContoh: /balance tim24.6840", chat_id)
            return

        username = parts[1].strip().lstrip('@')
        address = resolve_username(username)
        if not address:
            send_telegram(f"Username <b>{username}</b> tidak ditemukan.", chat_id)
            return

        balance = get_balance(contract, address, decimals)
        if balance is not None:
            msg = (
                f"💰 <b>{username}</b>\n"
                f"Address: <code>{address}</code>\n"
                f"Balance: <b>{balance:.4f} {symbol}</b>"
            )
        else:
            msg = f"Gagal cek balance untuk <b>{username}</b>"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": f"refresh_balance:{username}"}
        ]]}
        send_telegram(msg, chat_id, reply_markup=keyboard)

    elif cmd == '/balanceall':
        current = load_wallets_for_chat(chat_id)

        if not current:
            send_telegram("Daftar tracking kosong.", chat_id)
            return

        msg = f"<b>Balance All ({len(current)} wallets):</b>\n\n"
        total = 0.0
        for addr, label in current.items():
            balance = get_balance(contract, addr, decimals)
            if balance is not None:
                total += balance
                msg += f"• <b>{label}</b>: {balance:.4f} {symbol}\n"
            else:
                msg += f"• <b>{label}</b>: ERROR\n"

        msg += f"\n<b>Total: {total:.4f} {symbol}</b>"

        keyboard = {"inline_keyboard": [
            [{"text": "➕ Add", "callback_data": "balanceall:add"}, {"text": "➖ Remove", "callback_data": "balanceall:remove"}, {"text": "🔄 Refresh", "callback_data": "balanceall:refresh"}]
        ]}
        send_telegram(msg, chat_id, reply_markup=keyboard)

    elif cmd == '/dev':
        try:
            checksum = Web3.to_checksum_address(DEV_ADDRESS)
            # WLD balance
            wld_balance = get_balance(contract, DEV_ADDRESS, decimals)
            wld_str = f"{wld_balance:.4f}" if wld_balance is not None else "ERROR"
            # ETH balance
            eth_raw = w3.eth.get_balance(checksum)
            eth_balance = eth_raw / (10 ** 18)
            eth_str = f"{eth_balance:.6f}"

            # Get USD prices
            try:
                price_url = 'https://api.coingecko.com/api/v3/simple/price?ids=worldcoin-wld,ethereum&vs_currencies=usd'
                price_req = urllib.request.Request(price_url, headers={'User-Agent': 'Mozilla/5.0'})
                price_resp = urllib.request.urlopen(price_req, timeout=10)
                prices = json.loads(price_resp.read().decode())
                wld_price = prices.get('worldcoin-wld', {}).get('usd', 0)
                eth_price = prices.get('ethereum', {}).get('usd', 0)
            except Exception:
                wld_price = 0
                eth_price = 0

            wld_usd = wld_balance * wld_price if wld_balance else 0
            eth_usd = eth_balance * eth_price
            total_usd = wld_usd + eth_usd

            msg = (
                f"🏦 <b>Dev Wallet</b>\n\n"
                f"Address: <code>{DEV_ADDRESS}</code>\n\n"
                f"WLD: <b>{wld_str} WLD</b> (${wld_usd:.2f})\n"
                f"ETH: <b>{eth_str} ETH</b> (${eth_usd:.2f})\n\n"
                f"💵 Total: <b>${total_usd:.2f}</b>\n\n"
                f"<i>WLD: ${wld_price:.4f} | ETH: ${eth_price:.2f}</i>"
            )
        except Exception as e:
            msg = f"Gagal cek dev wallet: {e}"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": "dev:refresh"}
        ]]}
        send_telegram(msg, chat_id, reply_markup=keyboard)

    elif cmd == '/est':
        # Estimasi saldo habis berdasarkan TX keluar dari dev wallet
        try:
            checksum = Web3.to_checksum_address(DEV_ADDRESS)
            wld_balance = get_balance(contract, DEV_ADDRESS, decimals)

            if wld_balance is None or wld_balance == 0:
                send_telegram("Saldo dev wallet 0 atau gagal dicek.", chat_id)
                return

            # Ambil TX keluar (Transfer dari dev address) dalam 24 jam terakhir
            current_block = w3.eth.block_number
            # World Chain ~2 detik per block, 24 jam = 43200 blocks
            blocks_24h = 43200
            from_block = max(0, current_block - blocks_24h)

            padded_from = "0x" + DEV_ADDRESS[2:].lower().zfill(64)

            logs = w3.eth.get_logs({
                'fromBlock': from_block,
                'toBlock': current_block,
                'address': Web3.to_checksum_address(WLD_CONTRACT_ADDRESS),
                'topics': [TRANSFER_TOPIC, padded_from, None]
            })

            if not logs:
                send_telegram(
                    f"📊 <b>Estimasi Saldo Dev</b>\n\n"
                    f"Saldo: <b>{wld_balance:.4f} WLD</b>\n\n"
                    f"Tidak ada TX keluar dalam 24 jam terakhir.\n"
                    f"Tidak bisa menghitung estimasi.",
                    chat_id
                )
                return

            # Hitung total WLD keluar dan waktu
            total_out = 0.0
            first_block = logs[0]['blockNumber']
            last_block_tx = logs[-1]['blockNumber']

            for log in logs:
                amount_raw = int(log['data'].hex(), 16)
                amount = amount_raw / (10 ** decimals)
                total_out += amount

            # Hitung durasi antara first dan last TX (dalam detik)
            # Estimasi: 2 detik per block di World Chain
            block_diff = current_block - first_block
            duration_seconds = block_diff * 2

            if duration_seconds == 0 or total_out == 0:
                send_telegram("Tidak cukup data untuk estimasi.", chat_id)
                return

            # Rate per jam
            duration_hours = duration_seconds / 3600
            rate_per_hour = total_out / duration_hours

            # Estimasi waktu habis
            hours_remaining = wld_balance / rate_per_hour
            minutes_remaining = (hours_remaining % 1) * 60

            # Waktu habis
            import datetime
            now_utc = datetime.datetime.utcnow()
            habis_utc = now_utc + datetime.timedelta(hours=hours_remaining)
            habis_wib = habis_utc + datetime.timedelta(hours=7)

            msg = (
                f"📊 <b>Estimasi Saldo Dev</b>\n\n"
                f"Saldo: <b>{wld_balance:.4f} WLD</b>\n"
                f"TX keluar (24h): <b>{total_out:.4f} WLD</b> ({len(logs)} tx)\n"
                f"Rate: <b>{rate_per_hour:.4f} WLD/jam</b>\n\n"
                f"⏳ Habis dalam: <b>{int(hours_remaining)} jam {int(minutes_remaining)} menit</b>\n\n"
                f"🕐 Perkiraan habis:\n"
                f"   WIB: <b>{habis_wib.strftime('%d/%m/%Y %H:%M')}</b>\n"
                f"   UTC: <b>{habis_utc.strftime('%d/%m/%Y %H:%M')}</b>"
            )
        except Exception as e:
            msg = f"Gagal menghitung estimasi: {e}"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": "est:refresh"}
        ]]}
        send_telegram(msg, chat_id, reply_markup=keyboard)

    else:
        send_telegram("Command tidak dikenal. Ketik /help untuk bantuan.", chat_id)


# ============ CALLBACK HANDLER ============

def handle_callback(callback_id, chat_id, message_id, data, w3, contract, decimals, symbol):
    """Handle inline keyboard callback."""
    if chat_id not in ALLOWED_CHAT_IDS:
        answer_callback(callback_id, "⛔ Akses ditolak.")
        return

    # /balanceall refresh
    if data == "balanceall:refresh":
        answer_callback(callback_id, "🔄 Refreshing...")
        current = load_wallets_for_chat(chat_id)
        if not current:
            edit_telegram_message(chat_id, message_id, "Daftar tracking kosong.")
            return

        msg = f"<b>Balance All ({len(current)} wallets):</b>\n\n"
        total = 0.0
        for addr, label in current.items():
            balance = get_balance(contract, addr, decimals)
            if balance is not None:
                total += balance
                msg += f"• <b>{label}</b>: {balance:.4f} {symbol}\n"
            else:
                msg += f"• <b>{label}</b>: ERROR\n"

        msg += f"\n<b>Total: {total:.4f} {symbol}</b>"
        keyboard = {"inline_keyboard": [
            [{"text": "➕ Add", "callback_data": "balanceall:add"}, {"text": "➖ Remove", "callback_data": "balanceall:remove"}, {"text": "🔄 Refresh", "callback_data": "balanceall:refresh"}]
        ]}
        edit_telegram_message(chat_id, message_id, msg, reply_markup=keyboard)

    # /balanceall add
    elif data == "balanceall:add":
        answer_callback(callback_id, "")
        send_telegram("Ketik /add &lt;username&gt; untuk menambahkan wallet.\nContoh: /add tim24.6840", chat_id)

    # /balanceall remove - tampilkan pilihan username
    elif data == "balanceall:remove":
        answer_callback(callback_id, "")
        current = load_wallets_for_chat(chat_id)
        if not current:
            send_telegram("Daftar tracking kosong.", chat_id)
            return

        buttons = []
        for addr, label in current.items():
            buttons.append([{"text": f"❌ {label}", "callback_data": f"confirm_remove:{label}"}])
        buttons.append([{"text": "↩️ Batal", "callback_data": "remove:cancel"}])

        keyboard = {"inline_keyboard": buttons}
        send_telegram("<b>Pilih username untuk dihapus:</b>", chat_id, reply_markup=keyboard)

    # Confirm remove
    elif data.startswith("confirm_remove:"):
        username = data.split(":", 1)[1]
        answer_callback(callback_id, "")
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Ya, hapus", "callback_data": f"do_remove:{username}"},
            {"text": "❌ Batal", "callback_data": "remove:cancel"}
        ]]}
        edit_telegram_message(chat_id, message_id, f"Hapus <b>{username}</b> dari tracking?", reply_markup=keyboard)

    # Do remove
    elif data.startswith("do_remove:"):
        username = data.split(":", 1)[1]
        removed = remove_wallet_for_chat(chat_id, username)
        answer_callback(callback_id, f"✅ {username} dihapus" if removed else "Gagal menghapus")
        if removed:
            edit_telegram_message(chat_id, message_id, f"✅ <b>{username}</b> dihapus dari tracking.")
        else:
            edit_telegram_message(chat_id, message_id, f"Gagal menghapus <b>{username}</b>.")

    # Cancel remove
    elif data == "remove:cancel":
        answer_callback(callback_id, "Dibatalkan")
        edit_telegram_message(chat_id, message_id, "❌ Dibatalkan.")

    # /balance refresh
    elif data.startswith("refresh_balance:"):
        username = data.split(":", 1)[1]
        answer_callback(callback_id, "🔄 Refreshing...")
        address = resolve_username(username)
        if not address:
            edit_telegram_message(chat_id, message_id, f"Username <b>{username}</b> tidak ditemukan.")
            return

        balance = get_balance(contract, address, decimals)
        if balance is not None:
            msg = (
                f"💰 <b>{username}</b>\n"
                f"Address: <code>{address}</code>\n"
                f"Balance: <b>{balance:.4f} {symbol}</b>"
            )
        else:
            msg = f"Gagal cek balance untuk <b>{username}</b>"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": f"refresh_balance:{username}"}
        ]]}
        edit_telegram_message(chat_id, message_id, msg, reply_markup=keyboard)

    # /dev refresh
    elif data == "dev:refresh":
        answer_callback(callback_id, "🔄 Refreshing...")
        try:
            checksum = Web3.to_checksum_address(DEV_ADDRESS)
            wld_balance = get_balance(contract, DEV_ADDRESS, decimals)
            wld_str = f"{wld_balance:.4f}" if wld_balance is not None else "ERROR"
            eth_raw = w3.eth.get_balance(checksum)
            eth_balance = eth_raw / (10 ** 18)
            eth_str = f"{eth_balance:.6f}"

            try:
                price_url = 'https://api.coingecko.com/api/v3/simple/price?ids=worldcoin-wld,ethereum&vs_currencies=usd'
                price_req = urllib.request.Request(price_url, headers={'User-Agent': 'Mozilla/5.0'})
                price_resp = urllib.request.urlopen(price_req, timeout=10)
                prices = json.loads(price_resp.read().decode())
                wld_price = prices.get('worldcoin-wld', {}).get('usd', 0)
                eth_price = prices.get('ethereum', {}).get('usd', 0)
            except Exception:
                wld_price = 0
                eth_price = 0

            wld_usd = wld_balance * wld_price if wld_balance else 0
            eth_usd = eth_balance * eth_price
            total_usd = wld_usd + eth_usd

            msg = (
                f"🏦 <b>Dev Wallet</b>\n\n"
                f"Address: <code>{DEV_ADDRESS}</code>\n\n"
                f"WLD: <b>{wld_str} WLD</b> (${wld_usd:.2f})\n"
                f"ETH: <b>{eth_str} ETH</b> (${eth_usd:.2f})\n\n"
                f"💵 Total: <b>${total_usd:.2f}</b>\n\n"
                f"<i>WLD: ${wld_price:.4f} | ETH: ${eth_price:.2f}</i>"
            )
        except Exception as e:
            msg = f"Gagal cek dev wallet: {e}"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": "dev:refresh"}
        ]]}
        edit_telegram_message(chat_id, message_id, msg, reply_markup=keyboard)

    # /est refresh
    elif data == "est:refresh":
        answer_callback(callback_id, "🔄 Refreshing...")
        try:
            import datetime
            wld_balance = get_balance(contract, DEV_ADDRESS, decimals)

            if not wld_balance or wld_balance == 0:
                edit_telegram_message(chat_id, message_id, "Saldo dev wallet 0 atau gagal dicek.")
                return

            current_block = w3.eth.block_number
            blocks_24h = 43200
            from_block = max(0, current_block - blocks_24h)
            padded_from = "0x" + DEV_ADDRESS[2:].lower().zfill(64)

            logs = w3.eth.get_logs({
                'fromBlock': from_block,
                'toBlock': current_block,
                'address': Web3.to_checksum_address(WLD_CONTRACT_ADDRESS),
                'topics': [TRANSFER_TOPIC, padded_from, None]
            })

            if not logs:
                msg = (
                    f"📊 <b>Estimasi Saldo Dev</b>\n\n"
                    f"Saldo: <b>{wld_balance:.4f} WLD</b>\n\n"
                    f"Tidak ada TX keluar dalam 24 jam terakhir."
                )
            else:
                total_out = 0.0
                first_block = logs[0]['blockNumber']
                for log in logs:
                    amount_raw = int(log['data'].hex(), 16)
                    total_out += amount_raw / (10 ** decimals)

                block_diff = current_block - first_block
                duration_seconds = block_diff * 2
                duration_hours = duration_seconds / 3600

                if duration_hours > 0 and total_out > 0:
                    rate_per_hour = total_out / duration_hours
                    hours_remaining = wld_balance / rate_per_hour
                    minutes_remaining = (hours_remaining % 1) * 60

                    now_utc = datetime.datetime.utcnow()
                    habis_utc = now_utc + datetime.timedelta(hours=hours_remaining)
                    habis_wib = habis_utc + datetime.timedelta(hours=7)

                    msg = (
                        f"📊 <b>Estimasi Saldo Dev</b>\n\n"
                        f"Saldo: <b>{wld_balance:.4f} WLD</b>\n"
                        f"TX keluar (24h): <b>{total_out:.4f} WLD</b> ({len(logs)} tx)\n"
                        f"Rate: <b>{rate_per_hour:.4f} WLD/jam</b>\n\n"
                        f"⏳ Habis dalam: <b>{int(hours_remaining)} jam {int(minutes_remaining)} menit</b>\n\n"
                        f"🕐 Perkiraan habis:\n"
                        f"   WIB: <b>{habis_wib.strftime('%d/%m/%Y %H:%M')}</b>\n"
                        f"   UTC: <b>{habis_utc.strftime('%d/%m/%Y %H:%M')}</b>"
                    )
                else:
                    msg = "Tidak cukup data untuk estimasi."

        except Exception as e:
            msg = f"Gagal menghitung estimasi: {e}"

        keyboard = {"inline_keyboard": [[
            {"text": "🔄 Refresh", "callback_data": "est:refresh"}
        ]]}
        edit_telegram_message(chat_id, message_id, msg, reply_markup=keyboard)


# ============ THREADS ============

def telegram_bot_thread(w3, contract, decimals, symbol):
    """Thread untuk handle Telegram commands."""
    print("[BOT] Telegram bot listener started")
    offset = None

    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update['update_id'] + 1

                # Handle callback query (inline keyboard)
                callback = update.get('callback_query')
                if callback:
                    cb_id = callback['id']
                    cb_chat_id = str(callback.get('message', {}).get('chat', {}).get('id', ''))
                    cb_msg_id = callback.get('message', {}).get('message_id')
                    cb_data = callback.get('data', '')
                    print(f"[BOT] Callback: {cb_data} from {cb_chat_id}")
                    handle_callback(cb_id, cb_chat_id, cb_msg_id, cb_data, w3, contract, decimals, symbol)
                    continue

                # Handle message command
                msg = update.get('message', {})
                text = msg.get('text', '')
                chat_id = msg.get('chat', {}).get('id')

                if text and chat_id:
                    # Hanya proses pesan yang dimulai dengan /
                    if not text.startswith('/'):
                        continue
                    # Di grup, skip jika command ditujukan ke bot lain
                    chat_type = msg.get('chat', {}).get('type', 'private')
                    if chat_type in ('group', 'supergroup'):
                        cmd_part = text.split()[0]
                        if '@' in cmd_part and '@TrackingAkunWLD_bot' not in cmd_part:
                            continue
                    print(f"[BOT] Command: {text} from {chat_id}")
                    handle_command(str(chat_id), text, w3, contract, decimals, symbol)

        except Exception as e:
            print(f"[BOT ERROR] {e}")
            time.sleep(5)


def tracker_thread(w3, contract, decimals, symbol):
    """Thread untuk tracking TX masuk - kirim notif ke chat yang punya address."""
    print("[TRACKER] TX tracker started")

    # Load processed TX
    processed_tx = load_processed_tx()
    print(f"[TRACKER] Loaded {len(processed_tx)} processed TX")

    last_block = get_last_block()
    if last_block is None:
        last_block = w3.eth.block_number
        save_last_block(last_block)

    print(f"[TRACKER] Start block: {last_block}")

    while True:
        try:
            current_block = w3.eth.block_number

            if current_block > last_block:
                from_block = last_block + 1
                to_block = min(current_block, from_block + 999)

                # Load semua wallets dari semua chat
                with wallets_lock:
                    all_wallets = load_all_wallets()

                # Track user wallets
                for addr, chat_list in all_wallets.items():
                    padded_addr = "0x" + addr[2:].lower().zfill(64)

                    try:
                        logs = w3.eth.get_logs({
                            'fromBlock': from_block,
                            'toBlock': to_block,
                            'address': Web3.to_checksum_address(WLD_CONTRACT_ADDRESS),
                            'topics': [TRANSFER_TOPIC, None, padded_addr]
                        })

                        for log in logs:
                            tx_hash = log['transactionHash'].hex()

                            # Skip if already processed
                            if tx_hash in processed_tx:
                                continue

                            from_addr = "0x" + log['topics'][1].hex()[-40:]
                            to_addr = "0x" + log['topics'][2].hex()[-40:]
                            amount_raw = int(log['data'].hex(), 16)
                            amount = amount_raw / (10 ** decimals)
                            block = log['blockNumber']

                            # Mark as processed
                            processed_tx.add(tx_hash)
                            save_processed_tx(tx_hash)

                            # Kirim notif ke setiap chat yang punya address ini
                            for chat_info in chat_list:
                                msg = (
                                    f"💰 <b>WLD Received!</b>\n\n"
                                    f"To: <b>{chat_info['label']}</b>\n"
                                    f"Address: <code>{to_addr}</code>\n"
                                    f"From: <code>{from_addr[:6]}...{from_addr[-4:]}</code>\n"
                                    f"Amount: <b>{amount:.4f} {symbol}</b>\n"
                                    f"Block: {block}\n"
                                    f"TX: <code>{tx_hash}</code>\n"
                                    f"Explorer: https://worldscan.org/tx/{tx_hash}"
                                )
                                print(f"[TX IN] {chat_info['label']} +{amount:.4f} {symbol} -> chat {chat_info['chat_id']}")
                                send_telegram(msg, chat_info['chat_id'])

                    except Exception as e:
                        print(f"[TRACKER ERROR] {addr}: {e}")

                # Track DEV wallet - notif jika WLD masuk > 20k
                try:
                    dev_padded = "0x" + DEV_ADDRESS[2:].lower().zfill(64)
                    dev_logs = w3.eth.get_logs({
                        'fromBlock': from_block,
                        'toBlock': to_block,
                        'address': Web3.to_checksum_address(WLD_CONTRACT_ADDRESS),
                        'topics': [TRANSFER_TOPIC, None, dev_padded]
                    })

                    for log in dev_logs:
                        tx_hash = log['transactionHash'].hex()

                        # Skip if already processed
                        if tx_hash in processed_tx:
                            continue

                        amount_raw = int(log['data'].hex(), 16)
                        amount = amount_raw / (10 ** decimals)

                        if amount >= 20000:
                            from_addr = "0x" + log['topics'][1].hex()[-40:]

                            # Mark as processed
                            processed_tx.add(tx_hash)
                            save_processed_tx(tx_hash)

                            # Get total saldo sekarang
                            dev_balance = get_balance(contract, DEV_ADDRESS, decimals)

                            # Get USD price
                            try:
                                price_url = 'https://api.coingecko.com/api/v3/simple/price?ids=worldcoin-wld&vs_currencies=usd'
                                price_req = urllib.request.Request(price_url, headers={'User-Agent': 'Mozilla/5.0'})
                                price_resp = urllib.request.urlopen(price_req, timeout=10)
                                prices = json.loads(price_resp.read().decode())
                                wld_price = prices.get('worldcoin-wld', {}).get('usd', 0)
                            except Exception:
                                wld_price = 0

                            total_usd = dev_balance * wld_price if dev_balance else 0

                            msg = (
                                f"🚨 <b>Saldo DEV ISI</b>\n\n"
                                f"Total isi: <b>{amount:.4f} WLD</b>\n"
                                f"Total saldo: <b>{dev_balance:.4f} WLD</b> (${total_usd:.2f})\n\n"
                                f"From: <code>{from_addr[:6]}...{from_addr[-4:]}</code>\n"
                                f"TX: <code>{tx_hash}</code>"
                            )

                            print(f"[DEV ISI] +{amount:.4f} WLD")
                            # Kirim ke semua allowed chat
                            for cid in ALLOWED_CHAT_IDS:
                                send_telegram(msg, cid)

                except Exception as e:
                    print(f"[TRACKER ERROR] Dev wallet: {e}")

                last_block = to_block
                save_last_block(last_block)

        except Exception as e:
            print(f"[TRACKER ERROR] {e}")

        time.sleep(POLL_INTERVAL)


# ============ MAIN ============

def main():
    print("=== WLD Tracker + Telegram Bot ===\n")

    # Buat data directory
    os.makedirs(DATA_DIR, exist_ok=True)

    # Init Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("Gagal terhubung ke World Chain RPC.")
        return

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(WLD_CONTRACT_ADDRESS), abi=ERC20_ABI
    )

    try:
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
    except Exception as e:
        print(f"Gagal mendapatkan info token: {e}")
        return

    print(f"Terhubung ke World Chain (block: {w3.eth.block_number})")
    print(f"Token: {symbol} ({decimals} decimals)\n")

    # Kirim notif start
    send_telegram(
        f"🟢 <b>WLD Tracker Started</b>\n"
        f"Commands: /help"
    )

    # Start threads
    bot_t = threading.Thread(target=telegram_bot_thread, args=(w3, contract, decimals, symbol), daemon=True)
    tracker_t = threading.Thread(target=tracker_thread, args=(w3, contract, decimals, symbol), daemon=True)

    bot_t.start()
    tracker_t.start()

    print("[MAIN] Bot + Tracker running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping...")
        send_telegram("🔴 <b>WLD Tracker Stopped</b>")


if __name__ == "__main__":
    main()
