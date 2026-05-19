import sys
import os
import json
import urllib.request
import urllib.error
from web3 import Web3

# Konfigurasi
RPC_URL = "https://worldchain-mainnet.g.alchemy.com/public"
WLD_CONTRACT_ADDRESS = "0x2cFc85d8E48F8EAB294be644d9E25C3030863003"
USERNAMES_API = "https://usernames.worldcoin.org/api/v1"
WALLETS_FILE = "wallets.txt"

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


def init_web3():
    """Inisialisasi Web3 dan contract."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("Gagal terhubung ke World Chain RPC.")
        return None, None, None, None

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(WLD_CONTRACT_ADDRESS), abi=ERC20_ABI
    )

    try:
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
    except Exception as e:
        print(f"Gagal mendapatkan info token: {e}")
        return None, None, None, None

    return w3, contract, decimals, symbol


def get_balance(contract, address, decimals):
    """Get WLD balance."""
    try:
        checksum = Web3.to_checksum_address(address)
        raw = contract.functions.balanceOf(checksum).call()
        return raw / (10 ** decimals)
    except Exception:
        return None


def load_wallets():
    """Load existing wallets from wallets.txt."""
    wallets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), WALLETS_FILE)
    wallets = {}  # address -> username
    if os.path.exists(wallets_path):
        with open(wallets_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    wallets[parts[0].lower()] = parts[1]
                elif parts[0].startswith('0x'):
                    wallets[parts[0].lower()] = ''
    return wallets


def save_wallet(address, username):
    """Simpan address ke wallets.txt."""
    wallets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), WALLETS_FILE)
    wallets = load_wallets()

    if address.lower() not in wallets:
        with open(wallets_path, 'a') as f:
            f.write(f"{address} {username}\n")


def scan(file_path):
    """Scan WLD balance dari file username.txt, resolve address, simpan ke wallets.txt."""
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' tidak ditemukan.")
        return

    with open(file_path, 'r') as f:
        usernames = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not usernames:
        print("File kosong.")
        return

    print(f"=== WLD Balance Checker ===\n")
    print(f"Jumlah username: {len(usernames)}")

    w3, contract, decimals, symbol = init_web3()
    if not w3:
        return

    print(f"Terhubung ke World Chain\n")
    print(f"{'No':<5} {'Username':<25} {'Address':<45} {'Balance':>15}")
    print("=" * 95)

    total_balance = 0.0
    success_count = 0
    error_count = 0

    for idx, username in enumerate(usernames, 1):
        username = username.strip().lstrip('@')
        address = resolve_username(username)

        if not address:
            error_count += 1
            print(f"{idx:<5} {username:<25} {'NOT FOUND':<45} {'-':>15}")
            continue

        # Simpan address ke wallets.txt
        save_wallet(address, username)

        balance = get_balance(contract, address, decimals)

        if balance is not None:
            success_count += 1
            total_balance += balance
            print(f"{idx:<5} {username:<25} {address:<45} {balance:.4f} {symbol}")
        else:
            error_count += 1
            print(f"{idx:<5} {username:<25} {address:<45} {'ERROR':>15}")

    print("=" * 95)
    print(f"\n{'SUMMARY':=^50}")
    print(f"  Total dicek        : {success_count + error_count}")
    print(f"  Berhasil           : {success_count}")
    print(f"  Gagal              : {error_count}")
    print(f"  Total Balance      : {total_balance:.4f} {symbol}")
    print(f"{'':=^50}")
    print(f"\n  Address tersimpan di: {WALLETS_FILE}")


if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "username.txt"
    )
    scan(file_path)
