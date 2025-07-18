# backend/intent.py
import re

def detect_intent(text):
    text = text.lower()

    if "password" in text and "reset" in text:
        return "password_reset"
    elif "order" in text and ("status" in text or "track" in text):
        return "order_status"
    elif "cancel" in text:
        return "order_cancellation"
    elif "refund" in text:
        return "refund_request"
    else:
        return "general_query"
