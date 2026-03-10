#!/usr/bin/env python3
"""Register or check registration on the Modelionn subnet.

Usage:
    python scripts/register.py                    # interactive
    python scripts/register.py --network test     # testnet
    python scripts/register.py --wallet-name mywallet --wallet-hotkey myhotkey
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Register on the Modelionn Bittensor subnet")
    parser.add_argument("--network", default="test", choices=["finney", "test", "local"])
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--wallet-name", default="default")
    parser.add_argument("--wallet-hotkey", default="default")
    args = parser.parse_args()

    try:
        import bittensor as bt  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: bittensor not installed. Run: pip install 'modelionn[bittensor]'")
        sys.exit(1)

    wallet = bt.wallet(name=args.wallet_name, hotkey=args.wallet_hotkey)
    sub = bt.subtensor(network=args.network)
    mg = sub.metagraph(netuid=args.netuid)

    hotkey = wallet.hotkey.ss58_address
    print(f"Wallet:  {args.wallet_name}/{args.wallet_hotkey}")
    print(f"Hotkey:  {hotkey}")
    print(f"Network: {args.network}  netuid={args.netuid}")
    print(f"Neurons: {mg.n}")
    print()

    if hotkey in mg.hotkeys:
        uid = mg.hotkeys.index(hotkey)
        stake = float(mg.S[uid])
        print(f"✓ Already registered — uid={uid}  stake={stake:.4f} τ")
    else:
        print("Not registered. Attempting registration…")
        success = sub.register(wallet=wallet, netuid=args.netuid)
        if success:
            mg.sync(subtensor=sub)
            uid = mg.hotkeys.index(hotkey)
            print(f"✓ Registered — uid={uid}")
        else:
            print("✗ Registration failed. You may need more stake or retry later.")
            sys.exit(1)


if __name__ == "__main__":
    main()
