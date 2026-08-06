"""Shared site directory for the Belvoire Chocolatier demo -- (lat, lon) per
named facility. Single source of truth: the simulators import this to place
trips, and the app imports it to plot Origin/Destination on the dashboard map."""

SITES: dict[str, tuple[float, float]] = {
    "Turin Production Facility": (45.0703, 7.6869),
    "Antwerp Cocoa Processing Plant": (51.2194, 4.4025),
    "Rotterdam Distribution Hub": (51.9225, 4.4792),
    "Frankfurt Regional DC": (50.1109, 8.6821),
    "Lyon Cold Storage": (45.7640, 4.8357),
    "Milan Distribution Center": (45.4642, 9.1900),
    "Vienna Regional DC": (48.2082, 16.3738),
}
