"""Shared visual constants for the PPTX report builder -- one place to hold
the brand palette (matches frontend/src/styles/theme.css) and layout numbers
so report_generator.py and chart_xml.py never hardcode a hex or an Inches()
value independently."""
from pptx.util import Inches

SLIDE_W = Inches(10)
SLIDE_H = Inches(7.5)
HEADER_HEIGHT = Inches(0.7)
CHART_TOP = Inches(1.15)

FONT_HEADING = "Calibri"  # safe font (ships with Office, renders true-to-width)
PROGRAM_TITLE = "Program Manager AI — Cold Chain Analysis"

# Hex values below mirror frontend/src/styles/theme.css so the exported deck
# reads as the same product as the web app.
BAR_COLOR_HEX = "152C73"       # --carrier-blue
LINE_COLOR_HEX = "1891F6"      # --carrier-light-blue
WHITE_HEX = "FFFFFF"
DARK_TEXT_HEX = "1B2333"       # --color-text
MUTED_TEXT_HEX = "5B6478"      # --color-text-muted
REFERENCE_LINE_COLOR_HEX = "C62828"  # --color-error

# Categorical slots for a grouped-bar chart (one color per series) -- ordered
# so adjacent slots stay distinguishable; cap usage at this length and fold
# any remainder into "Other" rather than generating more hues.
BAR_PALETTE_HEX = ["152C73", "1891F6", "6F42C1", "0F8B8D", "8A5A10", "1A8F5E"]
MAX_GROUPED_SERIES = len(BAR_PALETTE_HEX)

Y_AXIS_SHIPMENT_COUNT_LABEL = "Shipments"
