import os
import time
import requests
from web3 import Web3

RPC_URL = "https://worldchain-mainnet.g.alchemy.com/public"

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEV_WALLET = os.getenv("DEV_WALLET")

WLD_CONTRACT = "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"

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
    }
]


def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message
        }, timeout=15)

    except Exception as e:
        print(f"Telegram Error: {e}")


w3 = Web3(Web3.HTTPProvider(RPC_URL))

if not w3.is_connected():
    print("RPC gagal connect")
    raise SystemExit

contract = w3.eth.contract(
    address=Web3.to_checksum_address(WLD_CONTRACT),
    abi=ERC20_ABI
)

wallet = Web3.to_checksum_address(DEV_WALLET)
decimals = contract.functions.decimals().call()

print("=== WLD DEV MONITOR STARTED ===")
print(f"Wallet: {wallet}")

send_telegram(
    f"🚀 WLD Monitor Started\n"
    f"Wallet: {wallet}"
)

last_balance = None

while True:
    try:
        raw_balance = contract.functions.balanceOf(wallet).call()
        balance = raw_balance / (10 ** decimals)

        if last_balance is None:
            last_balance = balance
            print(f"Balance awal: {balance:.4f} WLD")

        else:
            if balance > last_balance:
                diff = balance - last_balance

                msg = (
                    f"🟢 DEV ISI SALDO\n\n"
                    f"Wallet: {wallet}\n"
                    f"Masuk : {diff:.4f} WLD\n"
                    f"Saldo : {balance:.4f} WLD"
                )

                print(msg)
                send_telegram(msg)

            elif balance < last_balance:
                diff = last_balance - balance

                msg = (
                    f"🔴 DEV TRANSFER KELUAR\n\n"
                    f"Wallet: {wallet}\n"
                    f"Keluar: {diff:.4f} WLD\n"
                    f"Saldo : {balance:.4f} WLD"
                )

                print(msg)
                send_telegram(msg)

            last_balance = balance

        time.sleep(15)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(10)