from fastapi import Request


def is_localhost(request: Request) -> bool:
    return request.client.host in ("127.0.0.1", "::1")