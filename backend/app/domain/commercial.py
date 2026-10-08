from dataclasses import dataclass


@dataclass(frozen=True)
class CommercialDisclosure:
    promotes_own_brand: bool = False
    promotes_third_party: bool = False

    @property
    def enabled(self) -> bool:
        return self.promotes_own_brand or self.promotes_third_party

    def validate(self, *, privacy: str) -> None:
        if self.promotes_third_party and privacy == "SELF_ONLY":
            raise ValueError("branded content cannot use SELF_ONLY")
