"""
usdc_verify.py

Verificación de pagos en USDC sobre la red Base — leyendo la blockchain
directamente, sin depender de Coinbase Commerce, Alchemy, ni ningún
servicio de terceros. Adaptado de la lógica ya probada en producción en
Inscrbd (inscrbd.xyz), recortada aquí solo a lo que TrustBoost necesita:
un solo chain (Base), un solo token (USDC).

Por qué esto es seguro sin un tercero: cualquier transacción en una
blockchain pública queda escrita para siempre y cualquiera puede
consultarla. Aquí simplemente le preguntamos a un nodo público de Base
"¿esta transacción existe, fue exitosa, y de verdad movió el monto
correcto a mi wallet?" — sin necesitar que nadie más confirme nada.
"""

import re
import httpx

RPC_BASE_URL = "https://mainnet.base.org"
USDC_BASE_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_DECIMALS = 6


def _parse_declared_amount(s: str):
    match = re.search(r"[\d,]+\.?\d*", s or "")
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _amount_matches(declared: str, actual: float) -> bool:
    parsed = _parse_declared_amount(declared)
    if parsed is None:
        return False
    tolerance = max(0.01, parsed * 0.02)  # 2%, o un centavo — lo que sea mayor
    return abs(parsed - actual) <= tolerance


async def verify_base_usdc_payment(tx_hash: str, expected_recipient: str, expected_amount: str) -> dict:
    """
    Confirma que tx_hash es una transferencia real y exitosa de USDC en Base,
    que llegó específicamente a expected_recipient, por al menos
    expected_amount (con una tolerancia pequeña).

    Devuelve {"ok": True, "amount": ..., "to": ...} o {"ok": False, "reason": ...}
    """
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash or ""):
        return {"ok": False, "reason": "eso no parece un hash de transacción válido — debe empezar con 0x seguido de 64 caracteres hexadecimales"}

    usdc_addr = USDC_BASE_CONTRACT.lower()

    async with httpx.AsyncClient(timeout=10) as client:
        receipt_resp = await client.post(
            RPC_BASE_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
            },
        )
        resp_json = receipt_resp.json()

        if "error" in resp_json:
            msg = resp_json["error"].get("message", "error desconocido de RPC") if isinstance(resp_json["error"], dict) else str(resp_json["error"])
            return {"ok": False, "reason": f"no se pudo consultar la blockchain: {msg}"}

        receipt = resp_json.get("result")
        if not isinstance(receipt, dict):
            return {"ok": False, "reason": "no se encontró esa transacción en Base — puede que aún esté confirmándose, o el hash sea incorrecto"}

        if receipt.get("status") != "0x1":
            return {"ok": False, "reason": "la transacción falló o no se confirmó"}

        candidate_logs = [
            log for log in receipt.get("logs", [])
            if log["address"].lower() == usdc_addr
            and log["topics"]
            and log["topics"][0].lower() == TRANSFER_TOPIC0
        ]
        if not candidate_logs:
            return {"ok": False, "reason": "no se encontró una transferencia de USDC en esta transacción"}

        expected_lower = expected_recipient.lower()
        transfer_log = next(
            (log for log in candidate_logs if ("0x" + log["topics"][2][-40:]).lower() == expected_lower),
            None,
        )
        if not transfer_log:
            return {"ok": False, "reason": f"no se encontró una transferencia de USDC hacia {expected_recipient} en esta transacción"}

        raw_value = int(transfer_log["data"], 16)
        amount = raw_value / (10 ** USDC_DECIMALS)

        if not _amount_matches(expected_amount, amount):
            return {"ok": False, "reason": f"el monto recibido (${amount:.4f}) no coincide con lo esperado (${expected_amount})"}

        return {"ok": True, "amount": amount, "to": expected_recipient}
