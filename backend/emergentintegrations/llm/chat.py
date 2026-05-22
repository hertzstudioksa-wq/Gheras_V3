"""Stub — replaces emergentintegrations for local development."""


class UserMessage:
    def __init__(self, content=None, image_url=None, **kwargs):
        self.content = content


class ImageContent:
    def __init__(self, **kwargs):
        pass


class LlmChat:
    def __init__(self, api_key=None, session_id=None, system_message=None, **kwargs):
        pass

    def with_model(self, *args, **kwargs):
        return self

    async def send(self, *args, **kwargs):
        raise NotImplementedError("emergentintegrations not available locally — use a direct API key instead.")

    async def send_message(self, *args, **kwargs):
        raise NotImplementedError("emergentintegrations not available locally — use a direct API key instead.")
