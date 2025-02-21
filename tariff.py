class Tariff:
    def __init__(self,
                 id: str, display_name: str, api_display_name: str, tariff_code_matcher: str,
                 url_tariff_name: str, switchable: bool):
        self.id = id  # Represents the unique identifier for the tariff.
        self.display_name = display_name  # The user-friendly name of the tariff for display purposes.
        self.api_display_name = api_display_name  # The name used for API interactions with the tariff.
        self.tariff_code_matcher = tariff_code_matcher  # A string used to match against current tariff names to determine applicability.
        self.url_tariff_name = url_tariff_name  # The tariff name formatted for use in URLs.
        self.switchable = switchable  # Whether this tariff can be switched to or not

    def matches(self, current_tariff_name: str) -> bool:
        """Check if the given tariff name matches the tariff code matcher."""
        return self.tariff_code_matcher.lower() in current_tariff_name.lower()

    def __eq__(self, other):
        """Compare two tariffs based on their ID."""
        if isinstance(other, Tariff):
            return self.id == other.id
        return False


TARIFFS = [
    Tariff("go", "Octopus Go", "Octopus Go", "go", "go", True), # Octopus Go
    Tariff("agile", "Octopus Agile", "Agile Octopus", "agile", "agile", True), # Octopus Agile
    Tariff("cosy", "Octopus Cosy", "Octopus Cosy", "cosy-octopus", "cosy", True), # Octopus Cosy
]
