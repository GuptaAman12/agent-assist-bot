from app.services.intent import detect_intent, detect_intents


def test_known_intents():
    cases = {
        "password_reset": "I forgot my password",
        "check_balance": "what is my account balance",
        "update_address": "change my shipping address",
        "update_email": "update my email address",
        "refund_request": "I want a refund",
        "cancel_order": "please cancel my order",
        "track_order": "track my order",
        "update_payment_method": "change my payment method",
        "account_locked": "my account is locked",
        "recover_username": "I forgot my username",
        "change_subscription": "upgrade my plan",
        "get_invoice": "send me a receipt",
        "technical_issue": "the app keeps crashing",
        "speak_to_agent": "talk to a real person",
    }
    for intent, text in cases.items():
        assert detect_intent(text) == intent, text


def test_unknown_intent():
    assert detect_intent("quantum pineapple submarine") == "unknown"


def test_case_insensitive():
    assert detect_intent("FORGOT MY PASSWORD") == "password_reset"


def test_first_match_wins_speak_to_agent():
    # "human" wins over "password" because speak_to_agent is listed first.
    assert detect_intent("I want a human to help with my password") == "speak_to_agent"


def test_detect_intents_returns_all():
    intents = detect_intents("change my email address and the app keeps crashing")
    assert "update_email" in intents
    assert "technical_issue" in intents


def test_detect_intents_empty_for_gibberish():
    assert detect_intents("quantum pineapple submarine") == []


def test_prefix_forms_still_match():
    # Left-boundary matching keeps verb/plural forms users actually say.
    assert detect_intent("the app keeps crashing") == "technical_issue"
    assert detect_intent("the app crashed again") == "technical_issue"
    assert detect_intent("I forgot my passwords") == "password_reset"
    assert detect_intent("tracking my order") == "track_order"
    assert detect_intent("order was cancelled") == "cancel_order"


def test_no_match_inside_longer_word():
    # "unlocked" is the opposite of locked; "rebalance" is not a balance query.
    assert detect_intent("how do I get my account unlocked") == "unknown"
    assert detect_intent("help me rebalance my portfolio") == "unknown"
    assert "account_locked" not in detect_intents("how do I get my account unlocked")


def test_email_address_labels_update_email():
    # "address" is a whole word inside "email address", so both entries match;
    # dict order (update_email first) must keep the singular label correct.
    assert detect_intent("change my email address") == "update_email"
