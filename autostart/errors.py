"""Error types that map onto the CLI exit codes."""


class ConfigError(Exception):
    """Invalid config or CLI arguments. Exit code 2."""

    def __init__(self, messages):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = [str(item) for item in messages if str(item)]
        super().__init__("\n".join(self.messages))


class StepError(Exception):
    """A single recovery step failed. Later steps may still run."""


class NotifyError(Exception):
    """The status webhook failed after retries."""


class CrontabError(Exception):
    """A marker block in the crontab is unbalanced. Nothing was written."""


class HostError(Exception):
    """A host command such as crontab failed. Exit code 1."""
