"""Dev email backend — prints the plain, unwrapped body for easy copying.

The standard console backend prints the fully MIME-encoded message, where
quoted-printable wraps long lines with `=` soft breaks — which corrupts links
when you copy them out of the terminal. This backend appends the raw
`message.body` (verification and reset links stay on one clean line).
"""

from typing import Any

from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend
from django.core.mail.message import EmailMessage


class EmailBackend(ConsoleEmailBackend):
    def write_message(self, message: EmailMessage) -> Any:
        result = super().write_message(message)
        self.stream.write("\n----- plain body (dev, safe to copy) -----\n")
        self.stream.write(str(message.body))
        self.stream.write("\n------------------------------------------\n")
        self.stream.flush()
        return result
