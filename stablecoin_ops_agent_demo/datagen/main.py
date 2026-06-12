from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic

from .config import Config, load_config
from .state import ScenarioState

BASE_REFERENCE_TIME_MS = 1760000000000

TOPIC_CUSTOMERS = "stablecoin_demo_customer_profiles"
TOPIC_MERCHANT_POLICIES = "stablecoin_demo_merchant_payment_policies"
TOPIC_WALLET_RISK = "stablecoin_demo_wallet_risk_profiles"
TOPIC_INVOICES = "stablecoin_demo_payment_invoices"
TOPIC_SUPPORT_CASES = "stablecoin_demo_support_case_events"
TOPIC_ONCHAIN_TRANSFERS = "stablecoin_demo_onchain_token_transfers"

CHAINS = ("ethereum", "base", "polygon", "arbitrum")
TOKENS = ("USDC", "USDT")
REGIONS = ("US", "EU", "LATAM", "APAC")
CUSTOMER_TIERS = ("STANDARD", "GOLD", "PLATINUM")
MERCHANT_SEGMENTS = ("marketplace", "travel", "gaming", "software", "luxury", "electronics")


@dataclass(frozen=True)
class CustomerProfile:
    event_time_ms: int
    customer_id: str
    customer_name: str
    customer_region: str
    customer_tier: str
    payer_wallet_address: str
    risk_score: int


@dataclass(frozen=True)
class MerchantPolicy:
    event_time_ms: int
    merchant_id: str
    merchant_name: str
    merchant_segment: str
    settlement_wallet_address: str
    default_chain: str
    default_token: str
    invoice_expiry_minutes: int
    required_confirmations: int
    auto_release_limit_minor: int


class DataGen:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.state = ScenarioState(cfg.state_file)
        self.producer = KafkaProducer(
            bootstrap_servers=cfg.kafka_bootstrap_servers,
            client_id="stablecoin-payment-ops-datagen",
            acks="all",
            retries=10,
            linger_ms=20,
            batch_size=32768,
            key_serializer=lambda x: x.encode("utf-8"),
            value_serializer=lambda x: json.dumps(x, separators=(",", ":")).encode("utf-8"),
        )
        self.customers: list[CustomerProfile] = []
        self.merchants: list[MerchantPolicy] = []

    def create_topics(self) -> None:
        if not self.cfg.create_topics:
            return
        admin = KafkaAdminClient(bootstrap_servers=self.cfg.kafka_bootstrap_servers)
        topics = [
            NewTopic(TOPIC_CUSTOMERS, num_partitions=3, replication_factor=1),
            NewTopic(TOPIC_MERCHANT_POLICIES, num_partitions=3, replication_factor=1),
            NewTopic(TOPIC_WALLET_RISK, num_partitions=3, replication_factor=1),
            NewTopic(TOPIC_INVOICES, num_partitions=6, replication_factor=1),
            NewTopic(TOPIC_SUPPORT_CASES, num_partitions=6, replication_factor=1),
            NewTopic(TOPIC_ONCHAIN_TRANSFERS, num_partitions=6, replication_factor=1),
        ]
        try:
            admin.create_topics(topics)
        except Exception:
            pass
        finally:
            admin.close()

    def bootstrap_reference_data(self) -> None:
        self.customers.clear()
        self.merchants.clear()
        for i in range(1, self.cfg.customer_count + 1):
            customer_id = f"cust_{i}"
            payer_wallet = deterministic_wallet("payer", i)
            risk_score = deterministic_risk_score(i)
            customer = CustomerProfile(
                event_time_ms=BASE_REFERENCE_TIME_MS,
                customer_id=customer_id,
                customer_name=f"Customer {i}",
                customer_region=REGIONS[i % len(REGIONS)],
                customer_tier=CUSTOMER_TIERS[i % len(CUSTOMER_TIERS)],
                payer_wallet_address=payer_wallet,
                risk_score=risk_score,
            )
            self.customers.append(customer)
            self._send(TOPIC_CUSTOMERS, customer_id, {
                "event_time_ms": customer.event_time_ms,
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "customer_region": customer.customer_region,
                "customer_tier": customer.customer_tier,
                "payer_wallet_address": customer.payer_wallet_address,
                "risk_score": customer.risk_score,
            })
            self._send(TOPIC_WALLET_RISK, payer_wallet, {
                "event_time_ms": BASE_REFERENCE_TIME_MS,
                "wallet_address": payer_wallet,
                "customer_id": customer_id,
                "wallet_risk_score": risk_score,
                "risk_band": risk_band(risk_score),
                "compliance_state": "BLOCKED" if risk_score >= 85 else "REVIEW" if risk_score >= 70 else "CLEAR",
                "risk_reason": risk_reason(risk_score),
            })

        for i in range(1, self.cfg.merchant_count + 1):
            merchant_id = f"m_{i}"
            merchant = MerchantPolicy(
                event_time_ms=BASE_REFERENCE_TIME_MS,
                merchant_id=merchant_id,
                merchant_name=f"Merchant {i}",
                merchant_segment=MERCHANT_SEGMENTS[i % len(MERCHANT_SEGMENTS)],
                settlement_wallet_address=deterministic_wallet("merchant_settlement", i),
                default_chain=CHAINS[i % len(CHAINS)],
                default_token="USDC",
                invoice_expiry_minutes=30,
                required_confirmations=3,
                auto_release_limit_minor=750_000_000,
            )
            self.merchants.append(merchant)
            self._send(TOPIC_MERCHANT_POLICIES, merchant_id, {
                "event_time_ms": merchant.event_time_ms,
                "merchant_id": merchant.merchant_id,
                "merchant_name": merchant.merchant_name,
                "merchant_segment": merchant.merchant_segment,
                "settlement_wallet_address": merchant.settlement_wallet_address,
                "default_chain": merchant.default_chain,
                "default_token": merchant.default_token,
                "invoice_expiry_minutes": merchant.invoice_expiry_minutes,
                "required_confirmations": merchant.required_confirmations,
                "auto_release_limit_minor": merchant.auto_release_limit_minor,
            })
        self.producer.flush()

    def generate_scenario(self, scenario_seq: int) -> None:
        rnd = random.Random(self.cfg.scenario_seed_base + scenario_seq)
        event_time_ms = max(now_ms(), BASE_REFERENCE_TIME_MS + scenario_seq * 10_000)
        customer = self.customers[scenario_seq % len(self.customers)]
        merchant = self.merchants[scenario_seq % len(self.merchants)]
        invoice_id = f"inv_{scenario_seq}"
        payment_order_id = f"payord_{scenario_seq}"
        payment_address = deterministic_wallet(f"invoice_deposit_{scenario_seq}", 1)
        expected_amount_minor = (25 + rnd.randint(0, 2474)) * 1_000_000

        invoice = {
            "event_time_ms": event_time_ms,
            "invoice_id": invoice_id,
            "payment_order_id": payment_order_id,
            "customer_id": customer.customer_id,
            "merchant_id": merchant.merchant_id,
            "payment_address": payment_address,
            "expected_payer_wallet_address": customer.payer_wallet_address,
            "expected_chain": merchant.default_chain,
            "expected_token": merchant.default_token,
            "expected_amount_minor": expected_amount_minor,
            "currency_code": "USD",
            "invoice_state": "OPEN",
            "created_time_ms": event_time_ms,
            "expires_time_ms": event_time_ms + merchant.invoice_expiry_minutes * 60_000,
            "fulfillment_state": "WAITING_FOR_PAYMENT",
        }
        self._send(TOPIC_INVOICES, invoice_id, invoice)

        outcome = choose_outcome(scenario_seq, customer.risk_score)
        if outcome != "NO_ONCHAIN_PAYMENT":
            self._emit_onchain_transfer(invoice, outcome, scenario_seq, 1)
            if outcome == "DUPLICATE_PAYMENT":
                self._emit_onchain_transfer(invoice, "VALID_PAYMENT", scenario_seq, 2)

        if outcome != "VALID_PAYMENT":
            support_time = event_time_ms + 9000
            self._send(TOPIC_SUPPORT_CASES, f"case_{scenario_seq}", {
                "event_time_ms": support_time,
                "support_case_id": f"case_{scenario_seq}",
                "invoice_id": invoice_id,
                "payment_order_id": payment_order_id,
                "customer_id": customer.customer_id,
                "merchant_id": merchant.merchant_id,
                "case_state": "OPEN",
                "case_category": support_category(outcome),
                "case_reason": support_reason(outcome),
                "updated_time_ms": support_time,
            })
        self.producer.flush()

    def run(self, max_events: int | None) -> None:
        self.create_topics()
        self.bootstrap_reference_data()

        generated = 0
        while max_events is None or generated < max_events:
            seq = self.state.next_scenario_seq()
            self.generate_scenario(seq)
            generated += 1
            if max_events is None:
                time.sleep(self.cfg.loop_sleep_ms / 1000.0)

    def _emit_onchain_transfer(self, invoice: dict[str, Any], outcome: str, scenario_seq: int, index: int) -> None:
        actual_chain = invoice["expected_chain"]
        actual_token = invoice["expected_token"]
        actual_wallet = invoice["expected_payer_wallet_address"]
        actual_amount = int(invoice["expected_amount_minor"])

        if outcome == "UNDERPAID":
            actual_amount = max(1_000_000, round(actual_amount * 0.87))
        elif outcome == "OVERPAID":
            actual_amount = round(actual_amount * 1.11)
        elif outcome == "WRONG_CHAIN":
            actual_chain = pick_different_chain(actual_chain)
        elif outcome == "WRONG_TOKEN":
            actual_token = "USDT" if actual_token == "USDC" else "USDC"
        elif outcome == "UNEXPECTED_PAYER_WALLET":
            actual_wallet = deterministic_wallet(f"unexpected_payer_{scenario_seq}", index)

        transfer_time = int(invoice["event_time_ms"]) + 5000 + index * 1000
        event_id = f"onchain_evt_{scenario_seq}_{index}"
        self._send(TOPIC_ONCHAIN_TRANSFERS, event_id, {
            "event_time_ms": transfer_time,
            "onchain_event_id": event_id,
            "chain_name": actual_chain,
            "block_number": 22_000_000 + scenario_seq + index,
            "block_hash": f"0xblock{hex64(scenario_seq + index)}",
            "tx_hash": f"0xtx{hex64(scenario_seq * 100 + index)}",
            "log_index": index,
            "block_time_ms": transfer_time,
            "confirmation_count": 6,
            "contract_address": token_contract(actual_chain, actual_token),
            "token_symbol": actual_token,
            "token_decimals": 6,
            "sender_address": actual_wallet,
            "receiver_address": invoice["payment_address"],
            "amount_minor": actual_amount,
            "amount_decimal_text": decimal_string(actual_amount),
            "is_removed": False,
            "ingest_time_ms": transfer_time + 500,
            "source_op": "insert",
        })

    def _send(self, topic: str, key: str, value: dict[str, Any]) -> None:
        self.producer.send(topic, key=key, value=value).get(timeout=30)


def now_ms() -> int:
    return int(time.time() * 1000)


def deterministic_wallet(namespace: str, value: int) -> str:
    digest = sha1(f"{namespace}:{value}".encode("utf-8")).hexdigest()
    return f"0x{digest[:40]}"


def deterministic_risk_score(i: int) -> int:
    digest = sha1(f"risk:{i}".encode("utf-8")).hexdigest()
    x = int(digest[:8], 16) % 100
    if x < 75:
        return x % 40
    if x < 94:
        return 40 + (x % 35)
    return 85 + (x % 15)


def risk_band(score: int) -> str:
    if score >= 85:
        return "HIGH"
    if score >= 70:
        return "ELEVATED"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def risk_reason(score: int) -> str:
    if score >= 85:
        return "High-risk wallet, sanctions proximity, or severe velocity anomaly"
    if score >= 70:
        return "Elevated transaction velocity or risky counterparty exposure"
    if score >= 40:
        return "Moderate risk based on wallet behavior"
    return "No material risk indicator"


def choose_outcome(scenario_seq: int, customer_risk_score: int) -> str:
    bucket = scenario_seq % 100
    if customer_risk_score >= 85:
        if bucket < 40:
            return "NO_ONCHAIN_PAYMENT"
        if bucket < 70:
            return "UNEXPECTED_PAYER_WALLET"
        return "VALID_PAYMENT"
    if bucket < 55:
        return "VALID_PAYMENT"
    if bucket < 65:
        return "NO_ONCHAIN_PAYMENT"
    if bucket < 75:
        return "UNDERPAID"
    if bucket < 82:
        return "OVERPAID"
    if bucket < 89:
        return "WRONG_CHAIN"
    if bucket < 95:
        return "WRONG_TOKEN"
    if bucket < 98:
        return "UNEXPECTED_PAYER_WALLET"
    return "DUPLICATE_PAYMENT"


def support_category(outcome: str) -> str:
    mapping = {
        "NO_ONCHAIN_PAYMENT": "CUSTOMER_CLAIMS_PAID",
        "UNDERPAID": "AMOUNT_MISMATCH",
        "OVERPAID": "AMOUNT_MISMATCH",
        "WRONG_CHAIN": "WRONG_CHAIN_PAYMENT",
        "WRONG_TOKEN": "WRONG_TOKEN_PAYMENT",
        "UNEXPECTED_PAYER_WALLET": "PAYER_WALLET_MISMATCH",
        "DUPLICATE_PAYMENT": "DUPLICATE_PAYMENT",
    }
    return mapping.get(outcome, "PAYMENT_EXCEPTION")


def support_reason(outcome: str) -> str:
    mapping = {
        "NO_ONCHAIN_PAYMENT": "Customer claims payment was sent, but no confirmed matching onchain transfer has arrived.",
        "UNDERPAID": "Confirmed payment amount is lower than invoice amount.",
        "OVERPAID": "Confirmed payment amount is higher than invoice amount.",
        "WRONG_CHAIN": "Confirmed transfer arrived on a different chain than expected.",
        "WRONG_TOKEN": "Confirmed transfer used a different stablecoin token than expected.",
        "UNEXPECTED_PAYER_WALLET": "Confirmed transfer came from a wallet different from expected payer wallet.",
        "DUPLICATE_PAYMENT": "Multiple confirmed transfers were detected for one invoice.",
    }
    return mapping.get(outcome, "Payment requires operational review.")


def pick_different_chain(expected_chain: str) -> str:
    for chain in CHAINS:
        if chain != expected_chain:
            return chain
    return "ethereum"


def token_contract(chain: str, token: str) -> str:
    if token == "USDC":
        if chain == "ethereum":
            return "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        if chain == "base":
            return "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
        if chain == "polygon":
            return "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
        if chain == "arbitrum":
            return "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
    return f"0x{token.lower()}_{chain}"


def hex64(seed: int) -> str:
    h = format(abs(seed), "x")
    return f"{'0' * max(0, 64 - len(h))}{h}"


def decimal_string(minor: int) -> str:
    whole = minor // 1_000_000
    frac = minor % 1_000_000
    return f"{whole}.{frac:06d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stablecoin payment ops data generator")
    parser.add_argument("--max-events", type=int, default=None, help="Stop after N scenarios")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()
    gen = DataGen(cfg)
    gen.run(args.max_events)


if __name__ == "__main__":
    main()
