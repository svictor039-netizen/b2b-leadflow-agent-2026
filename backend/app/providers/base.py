from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailMessage:
    to_address: str
    subject: str
    body: str
    from_address: str = "test@leadflow.local"
    metadata: dict = field(default_factory=dict)


@dataclass
class EmailSendResult:
    success: bool
    provider: str
    message_id: str
    sent_at: datetime
    simulated: bool = True
    detail: str = ""


class EmailProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def send(self, message: EmailMessage) -> EmailSendResult:
        pass


@dataclass
class CompanyRecord:
    name: str
    domain: str
    region: str
    niche: str
    contact_email: str
    description: str = ""
    website: str | None = None
    phone: str | None = None
    source_record_id: str | None = None
    source_url: str | None = None
    is_test_data: bool = True


class SourceAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def search(self, niche: str, region: str, limit: int = 30) -> list[CompanyRecord]:
        pass
