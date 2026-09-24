from typing import Dict, Any
from src.domain.schemas import ToolCallResult

class BankingToolsRegistry:
    """
    Simulated Core Banking & Fraud Prevention Tool Suite.
    Integrates with audit trail and provides safety constraints.
    """

    @staticmethod
    def lock_card(card_id: str, reason: str = "Suspected fraud") -> ToolCallResult:
        return ToolCallResult(
            tool_name="lock_card",
            success=True,
            output={
                "card_id": card_id,
                "status": "LOCKED",
                "reason": reason,
                "timestamp": "2026-09-24T12:00:00Z",
                "message": f"Card {card_id} has been securely frozen. All upcoming authorizations will be declined."
            }
        )

    @staticmethod
    def verify_transaction(transaction_id: str) -> ToolCallResult:
        return ToolCallResult(
            tool_name="verify_transaction",
            success=True,
            output={
                "transaction_id": transaction_id,
                "clearing_status": "PENDING_SETTLEMENT",
                "can_chargeback": True,
                "merchant_details": "Verified Merchant Network"
            }
        )

    @staticmethod
    def open_dispute(transaction_id: str, dispute_reason: str, amount: float) -> ToolCallResult:
        case_id = f"DISP-{transaction_id[-6:]}"
        return ToolCallResult(
            tool_name="open_dispute",
            success=True,
            output={
                "case_id": case_id,
                "transaction_id": transaction_id,
                "amount_held": amount,
                "dispute_reason": dispute_reason,
                "provisional_credit_issued": amount <= 200.0,
                "message": f"Dispute case {case_id} registered. Provisional credit evaluated."
            }
        )

    @staticmethod
    def send_security_sms(phone: str, customer_id: str, prompt_message: str) -> ToolCallResult:
        return ToolCallResult(
            tool_name="send_security_sms",
            success=True,
            output={
                "customer_id": customer_id,
                "target_phone": phone[-4:].rjust(len(phone), "*") if len(phone) > 4 else "****",
                "delivery_status": "DELIVERED",
                "message": prompt_message
            }
        )

    @classmethod
    def execute(cls, tool_name: str, parameters: Dict[str, Any]) -> ToolCallResult:
        if tool_name == "lock_card":
            return cls.lock_card(parameters.get("card_id", "CARD_DEFAULT"), parameters.get("reason", "Customer requested"))
        elif tool_name == "verify_transaction":
            return cls.verify_transaction(parameters.get("transaction_id", "TX_UNKNOWN"))
        elif tool_name == "open_dispute":
            return cls.open_dispute(
                parameters.get("transaction_id", "TX_UNKNOWN"),
                parameters.get("dispute_reason", "Unrecognized transaction"),
                float(parameters.get("amount", 0.0))
            )
        elif tool_name == "send_security_sms":
            return cls.send_security_sms(
                parameters.get("phone", "+15550000000"),
                parameters.get("customer_id", "CUST_DEFAULT"),
                parameters.get("prompt_message", "Security Alert")
            )
        else:
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                output={},
                error_message=f"Tool '{tool_name}' not recognized in safe tool registry."
            )
