"""Stub — replaces emergentintegrations for local development."""


class CheckoutSessionRequest:
    def __init__(self, **kwargs):
        pass


class StripeCheckout:
    def __init__(self, api_key=None, webhook_url=None, **kwargs):
        pass

    async def create_checkout_session(self, *args, **kwargs):
        raise NotImplementedError("Stripe via emergentintegrations not available locally.")

    async def get_checkout_status(self, *args, **kwargs):
        raise NotImplementedError("Stripe via emergentintegrations not available locally.")

    async def handle_webhook(self, *args, **kwargs):
        raise NotImplementedError("Stripe via emergentintegrations not available locally.")
