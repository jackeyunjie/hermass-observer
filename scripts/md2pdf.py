import markdown
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import re
import sys

# Register CJK font for macOS
pdfmetrics.registerFont(TTFont("PingFang", "/System/Library/Fonts/STHeiti Light.ttc", subfontIndex=0))

# Read markdown
with open("docs/MVP_MEETING_Q&A.md", "r", encoding="utf-8") as f:
    md_text = f.read()

# Convert markdown to HTML first
html_text = markdown.markdown(md_text, extensions=["tables"])

# Create PDF
doc = SimpleDocTemplate(
    "docs/MVP_MEETING_Q&A.pdf", pagesize=A4, rightMargin=60, leftMargin=60, topMargin=60, bottomMargin=40
)

styles = getSampleStyleSheet()

# Custom styles with CJK font
title_style = ParagraphStyle(
    "CustomTitle",
    parent=styles["Title"],
    fontName="PingFang",
    fontSize=20,
    spaceAfter=20,
    textColor=colors.HexColor("#1a1a2e"),
)
heading1_style = ParagraphStyle(
    "CustomH1",
    parent=styles["Heading1"],
    fontName="PingFang",
    fontSize=16,
    spaceAfter=12,
    spaceBefore=16,
    textColor=colors.HexColor("#16213e"),
)
heading2_style = ParagraphStyle(
    "CustomH2",
    parent=styles["Heading2"],
    fontName="PingFang",
    fontSize=13,
    spaceAfter=8,
    spaceBefore=12,
    textColor=colors.HexColor("#0f3460"),
)
body_style = ParagraphStyle(
    "CustomBody", parent=styles["Normal"], fontName="PingFang", fontSize=10, leading=16, spaceAfter=6
)
quote_style = ParagraphStyle(
    "CustomQuote",
    parent=styles["Normal"],
    fontName="PingFang",
    fontSize=9,
    leading=14,
    leftIndent=20,
    textColor=colors.HexColor("#5d6b82"),
)

story = []

# Parse HTML-like content manually
lines = html_text.split("\n")
i = 0
while i < len(lines):
    line = lines[i].strip()
    if not line:
        i += 1
        continue

    # Title
    if line.startswith("<h1>"):
        text = re.sub(r"<[^>]+>", "", line)
        story.append(Paragraph(text, title_style))
        story.append(Spacer(1, 10))
    # Heading 2
    elif line.startswith("<h2>"):
        text = re.sub(r"<[^>]+>", "", line)
        story.append(Paragraph(text, heading1_style))
    # Heading 3
    elif line.startswith("<h3>"):
        text = re.sub(r"<[^>]+>", "", line)
        story.append(Paragraph(text, heading2_style))
    # Blockquote
    elif line.startswith("<blockquote>"):
        text = re.sub(r"<[^>]+>", "", line)
        story.append(Paragraph(text, quote_style))
    # Table
    elif line.startswith("<table>"):
        table_rows = []
        in_table = True
        while in_table and i < len(lines):
            row_line = lines[i].strip()
            if "<tr>" in row_line:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_line)
                if cells:
                    table_rows.append([Paragraph(c, body_style) for c in cells])
            if "</table>" in row_line:
                in_table = False
            i += 1
        if table_rows:
            col_count = len(table_rows[0])
            col_widths = [doc.width / col_count] * col_count
            table = Table(table_rows, colWidths=col_widths)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f3f8")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                        ("FONTNAME", (0, 0), (-1, -1), "PingFang"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e6ef")),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 10))
        continue
    # Paragraph
    else:
        text = re.sub(r"<[^>]+>", "", line)
        if text:
            story.append(Paragraph(text, body_style))

    i += 1

doc.build(story)
print("✅ PDF generated: docs/MVP_MEETING_Q&A.pdf")
