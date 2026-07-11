"""
X402_DIRECT_VERIFY — additive on-chain payment verification for autonomous agents.

Adds a PARALLEL path to the existing CDP/PayAI facilitator flow:
  If a client envelope carries a real on-chain `transactionHash` (a payment it
  already settled to our wallet), verify the transfer directly against the chain
  RPC — NO facilitator JWT, NO CDP/PayAI dependency.

The facilitator path (CDP / PayAI / Bazaar settle) is LEFT INTACT and remains the
primary route. This module only adds an early-return branch when `transactionHash`
is present. It never touches Supabase, settlement, or existing payment logic.

Net effect: an external agent that discovers the service, signs x402, and pays
USDC on-chain directly to our wallet now receives HTTP 200 — fluid M2M adoption —
without coupling to the facilitator infrastructure.
"""
from __future__ import annotations
import json
import time
import httpx

# ── Chain RPCs (public, read-only; no auth, no key) ──────────────────────────
# Multiple Base RPCs as fallback — public RPCs (e.g. mainnet.base.org) are often
# rate-limited or blocked from cloud sandboxes, so we try several before giving up.
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base.llamarpc.com",
    "https://rpc.ankr.com/base",
    "https://base.meowrpc.com",
]
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# ERC-20 USDC contract addresses
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Minimal ERC-20 ABI (balanceOf/transferFrom not needed; we read Transfer logs)
ERC20_ABI = [{
    "anonymous": False, "name": "Transfer", "type": "event",
    "inputs": [
        {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": False, "name": "value", "type": "uint256"},
    ],
}]

# How long after the tx we still accept it as "fresh" (anti-stale).
# On-chain USDC transfers are final/irreversible, so we accept any historical
# valid transfer to our wallet. Kept generous (7d) only as a sanity bound, not
# a freshness requirement — the payment is final the moment it settles.
MAX_TX_AGE_SECONDS = 7 * 24 * 3600


def _is_hex(s: str) -> bool:
    s = (s or "").lower()
    if s.startswith("0x"):
        s = s[2:]
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


async def verify_onchain_direct(envelope: dict, pay_to: str, amount_micro: int,
                                network: str) -> tuple[bool, str]:
    """
    Verify an on-chain USDC transfer directly via public RPC.
    Returns (is_valid, payer_address).

    envelope: the decoded X-PAYMENT JSON. Must contain `transactionHash`.
    pay_to:   our wallet that must have RECEIVED the transfer.
    amount_micro: expected amount in microUSDC (6 decimals).
    network:  'eip155:8453' or 'solana:5eykt4UsFv8P8NJdTREpY1vzqKvdp'.
    """
    tx = envelope.get("transactionHash") or envelope.get("tx_hash") or envelope.get("transactionHash")
    if not tx:
        return False, ""
    if network.startswith("eip155:"):
        return await _verify_base(tx, pay_to, amount_micro)
    if network.startswith("solana:"):
        return await _verify_solana(tx, pay_to, amount_micro)
    return False, ""


async def _verify_base(tx: str, pay_to: str, amount_micro: int) -> tuple[bool, str]:
    if not _is_hex(tx):
        return False, ""
    last_err = ""
    for rpc in BASE_RPCS:
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.post(rpc, json={
                    "jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
                    "params": [tx],
                })
                data = r.json().get("result")
                if not data:
                    continue
                blk = (await c.post(rpc, json={
                    "jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber",
                    "params": [data.get("blockNumber"), False],
                })).json().get("result")
                ts = int(blk.get("timestamp", "0x0"), 16) if blk else 0
                if ts and (time.time() - ts) > MAX_TX_AGE_SECONDS:
                    print(f"[direct-verify] Base tx {tx[:10]} too old ({time.time()-ts:.0f}s)")
                    return False, ""
                pay_to_l = pay_to.lower()
                for log in data.get("logs", []):
                    if log.get("address", "").lower() != USDC_BASE.lower():
                        continue
                    topics = log.get("topics", [])
                    if len(topics) < 3:
                        continue
                    to_addr = "0x" + topics[2][26:]
                    if to_addr.lower() == pay_to_l:
                        value = int(log.get("data", "0x0"), 16)
                        if value >= amount_micro:
                            payer = "0x" + topics[1][26:]
                            print(f"[direct-verify] Base tx {tx[:10]} OK: {value} uUSDC to {pay_to_l[:10]}")
                            return True, payer
                return False, ""
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
            print(f"[direct-verify] Base RPC {rpc} error: {last_err}")
            continue
    print(f"[direct-verify] Base tx {tx[:10]} not verified on any RPC ({last_err})")
    return False, ""


async def _verify_solana(tx: str, pay_to: str, amount_micro: int) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(SOLANA_RPC, json={
                "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                "params": [tx, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            })
            data = r.json().get("result")
            if not data:
                return False, ""
            # Find a parsed SPL Transfer of USDC to pay_to with sufficient amount
            for instr in data.get("transaction", {}).get("message", {}).get("instructions", []):
                if instr.get("program") != "spl-token":
                    continue
                info = instr.get("parsed", {}).get("info", {})
                if (info.get("mint") == USDC_SOLANA and
                        info.get("destination") == pay_to and
                        int(info.get("tokenAmount", {}).get("amount", 0)) >= amount_micro):
                    return True, info.get("authority", info.get("source", ""))
            return False, ""
    except Exception as e:
        print(f"[direct-verify] Solana RPC error: {type(e).__name__}: {str(e)[:80]}")
        return False, ""
