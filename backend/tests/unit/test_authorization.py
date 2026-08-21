from backend.auth.authorization import is_authorized_for_order


def test_owner_can_access_their_own_order():
    assert is_authorized_for_order("cust_1", "12345") is True


def test_customer_cannot_access_another_customers_order():
    assert is_authorized_for_order("cust_1", "67890") is False


def test_anonymous_customer_is_never_authorized_for_a_known_order():
    assert is_authorized_for_order(None, "12345") is False


def test_unknown_order_id_is_treated_as_not_found_not_unauthorized():
    # Any customer (including anonymous) is allowed through for an order ID
    # that doesn't exist — the tool itself reports "not found"; this function
    # only blocks confirmed cross-customer access to a real order.
    assert is_authorized_for_order(None, "99999-does-not-exist") is True
    assert is_authorized_for_order("cust_1", "99999-does-not-exist") is True
