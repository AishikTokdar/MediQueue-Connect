import os
import json
import html
from datetime import datetime
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        HRFlowable,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


_CACHED_STYLES = None

def _get_styles():
    global _CACHED_STYLES
    if _CACHED_STYLES is not None:
        return _CACHED_STYLES

    styles = getSampleStyleSheet()

    NAVY = colors.HexColor("#1E3A8A")
    TEAL = colors.HexColor("#0D9488")
    SLATE_DARK = colors.HexColor("#1E293B")
    BORDER_COLOR = colors.HexColor("#E2E8F0")

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=NAVY,
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=TEAL,
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=NAVY,
        fontName="Helvetica-Bold",
    )

    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=SLATE_DARK,
        fontName="Helvetica",
    )

    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        textColor=NAVY,
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=6,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    cell_patient_style = ParagraphStyle(
        "CellPatient",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#0369A1"),
        fontName="Helvetica-Bold",
    )

    cell_doctor_style = ParagraphStyle(
        "CellDoctor",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#047857"),
        fontName="Helvetica-Bold",
    )

    cell_text_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=SLATE_DARK,
        fontName="Helvetica",
    )

    cell_ts_style = ParagraphStyle(
        "CellTS",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748B"),
        fontName="Helvetica",
    )

    footer_style = ParagraphStyle(
        "FooterText",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#94A3B8"),
        alignment=TA_CENTER,
        fontName="Helvetica-Oblique",
    )

    signoff_style = ParagraphStyle(
        "SignoffText",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=SLATE_DARK,
    )

    _CACHED_STYLES = {
        "styles": styles,
        "title": title_style,
        "subtitle": subtitle_style,
        "meta_label": meta_label_style,
        "meta_val": meta_val_style,
        "section": section_style,
        "table_header": table_header_style,
        "cell_patient": cell_patient_style,
        "cell_doctor": cell_doctor_style,
        "cell_text": cell_text_style,
        "cell_ts": cell_ts_style,
        "footer": footer_style,
        "signoff": signoff_style,
        "NAVY": NAVY,
        "TEAL": TEAL,
        "SLATE_DARK": SLATE_DARK,
        "SLATE_LIGHT": colors.HexColor("#F8FAFC"),
        "BORDER_COLOR": BORDER_COLOR,
    }
    return _CACHED_STYLES


def generate_transcript_pdf(
    session_id: str,
    doctor: str,
    patient: str,
    transcript_records: list[dict],
    output_path: Any,
    prescription: dict | None = None,
    patient_profile: dict | None = None,
) -> str:
    """
    Generates a beautifully styled, professional medical consultation summary PDF
    from a list of transcript record dicts.
    Saves to output_path and returns the absolute filepath (or 'in-memory').
    """
    if isinstance(output_path, (str, os.PathLike)):
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if not _REPORTLAB_AVAILABLE:
        if isinstance(output_path, (str, os.PathLike)):
            txt_path = str(output_path).replace(".pdf", ".txt") if str(output_path).endswith(".pdf") else str(output_path)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"MEDIQUEUE CONNECT - CONSULTATION SUMMARY\n{'='*55}\n")
                f.write(f"Session ID: {session_id}\nDoctor: Dr. {doctor}\nPatient: {patient}\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*55}\n\n")
                if prescription:
                    f.write(f"DIAGNOSIS: {prescription.get('diagnosis', 'N/A')}\n")
                    f.write(f"MEDICATIONS: {prescription.get('medications', [])}\n")
                    f.write(f"INSTRUCTIONS: {prescription.get('instructions', 'N/A')}\n\n")
                f.write("TRANSCRIPT:\n")
                for rec in transcript_records:
                    sender = rec.get("sender", "")
                    text = rec.get("text", "")
                    ts = rec.get("ts", "")
                    f.write(f"[{ts}] {sender}: {text}\n")
            return os.path.abspath(txt_path)
        else:
            output_path.write(b"MEDIQUEUE CONNECT - CONSULTATION SUMMARY\n")
            return "in-memory"

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    s_bundle = _get_styles()
    signoff_style = s_bundle["signoff"]
    title_style = s_bundle["title"]
    subtitle_style = s_bundle["subtitle"]
    meta_label_style = s_bundle["meta_label"]
    meta_val_style = s_bundle["meta_val"]
    section_style = s_bundle["section"]
    table_header_style = s_bundle["table_header"]
    cell_patient_style = s_bundle["cell_patient"]
    cell_doctor_style = s_bundle["cell_doctor"]
    cell_text_style = s_bundle["cell_text"]
    cell_ts_style = s_bundle["cell_ts"]
    footer_style = s_bundle["footer"]
    NAVY = s_bundle["NAVY"]
    TEAL = s_bundle["TEAL"]
    SLATE_DARK = s_bundle["SLATE_DARK"]
    SLATE_LIGHT = s_bundle["SLATE_LIGHT"]
    BORDER_COLOR = s_bundle["BORDER_COLOR"]

    elements = []

    elements.append(Paragraph("MediQueue Connect", subtitle_style))
    elements.append(Paragraph("Clinical Consultation Summary & Transcript", title_style))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceAfter=12))

    start_ts = "N/A"
    end_ts = "N/A"
    messages = []

    for rec in transcript_records:
        event = rec.get("event")
        ts = rec.get("ts", "")
        if event == "SESSION_START":
            start_ts = ts
        elif event == "SESSION_END":
            end_ts = ts
        elif "text" in rec and "sender" in rec:
            messages.append(rec)

    if end_ts == "N/A" and messages:
        end_ts = messages[-1].get("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    meta_data = [
        [
            Paragraph("Session ID:", meta_label_style),
            Paragraph(html.escape(session_id), meta_val_style),
            Paragraph("Consultation Date:", meta_label_style),
            Paragraph(html.escape(start_ts.split(" ")[0] if " " in start_ts else start_ts), meta_val_style),
        ],
        [
            Paragraph("Attending Doctor:", meta_label_style),
            Paragraph(f"Dr. {html.escape(doctor)}", meta_val_style),
            Paragraph("Patient Name/ID:", meta_label_style),
            Paragraph(html.escape(patient), meta_val_style),
        ],
        [
            Paragraph("Session Started:", meta_label_style),
            Paragraph(html.escape(start_ts), meta_val_style),
            Paragraph("Session Ended:", meta_label_style),
            Paragraph(html.escape(end_ts), meta_val_style),
        ],
        [
            Paragraph("Total Dialogue Count:", meta_label_style),
            Paragraph(f"{len(messages)} messages", meta_val_style),
            Paragraph("Security & Encryption:", meta_label_style),
            Paragraph("Fernet AES-128 / UDP Tunnel", meta_val_style),
        ],
    ]

    if patient_profile:
        bg = patient_profile.get("blood_group") or "Not recorded"
        allergies_list = patient_profile.get("allergies", [])
        all_display = ", ".join(allergies_list).upper() if allergies_list else "None recorded"
        meta_data.append([
            Paragraph("Blood Group:", meta_label_style),
            Paragraph(html.escape(bg), meta_val_style),
            Paragraph("Known Allergies:", meta_label_style),
            Paragraph(f"<b>{html.escape(all_display)}</b>", meta_val_style),
        ])

    meta_table = Table(meta_data, colWidths=[110, 160, 110, 160])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SLATE_LIGHT),
            ("BOX", (0, 0), (-1, -1), 1, BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    elements.append(meta_table)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("Session Dialogue Transcript", section_style))

    t_rows = [
        [
            Paragraph("Timestamp", table_header_style),
            Paragraph("Participant", table_header_style),
            Paragraph("Message / Clinical Communication", table_header_style),
        ]
    ]

    if not messages:
        t_rows.append([
            Paragraph("-", cell_ts_style),
            Paragraph("System", cell_patient_style),
            Paragraph("[No conversation messages were recorded for this session]", cell_text_style),
        ])
    else:
        for msg in messages:
            sender = msg.get("sender", "Unknown")
            text = msg.get("text", "")
            ts = msg.get("ts", "")

            sender_p = (
                Paragraph(f"Dr. {html.escape(sender)}", cell_doctor_style)
                if sender.lower() == doctor.lower()
                else Paragraph(html.escape(sender), cell_patient_style)
            )

            t_rows.append([
                Paragraph(html.escape(ts), cell_ts_style),
                sender_p,
                Paragraph(html.escape(text), cell_text_style),
            ])


    t_table = Table(t_rows, colWidths=[110, 110, 320])
    
    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_COLOR),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]

    for r_idx in range(1, len(t_rows)):
        bg = colors.HexColor("#FFFFFF") if r_idx % 2 == 1 else colors.HexColor("#F8FAFC")
        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), bg))

    t_table.setStyle(TableStyle(t_style))
    elements.append(t_table)
    elements.append(Spacer(1, 14))

    if prescription:
        elements.append(Paragraph("Clinical Prescription & Diagnosis (Rx)", section_style))
        diag_text = html.escape(prescription.get("diagnosis", "Unspecified"))
        inst_text = html.escape(prescription.get("instructions", "") or "None provided")
        rx_meta = [
            [
                Paragraph("Primary Diagnosis:", meta_label_style),
                Paragraph(f"<b>{diag_text}</b>", meta_val_style),
                Paragraph("Prescribing Physician:", meta_label_style),
                Paragraph(f"Dr. {html.escape(doctor)}", meta_val_style),
            ],
            [
                Paragraph("Clinical Advice / Diet:", meta_label_style),
                Paragraph(inst_text, meta_val_style),
                Paragraph("Rx Auth Token:", meta_label_style),
                Paragraph(f"RX-{session_id[:8].upper()}", meta_val_style),
            ],
        ]
        rx_meta_table = Table(rx_meta, colWidths=[120, 150, 120, 150])
        rx_meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#86EFAC")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBF7D0")),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(rx_meta_table)
        elements.append(Spacer(1, 8))

        meds = prescription.get("medications", [])
        if meds:
            rx_rows = [
                [
                    Paragraph("Medication Name", table_header_style),
                    Paragraph("Dosage", table_header_style),
                    Paragraph("Frequency", table_header_style),
                    Paragraph("Duration", table_header_style),
                    Paragraph("Notes", table_header_style),
                ]
            ]
            for m in meds:
                rx_rows.append([
                    Paragraph(f"<b>{html.escape(str(m.get('name', '')))}</b>", cell_text_style),
                    Paragraph(html.escape(str(m.get("dosage", ""))), cell_text_style),
                    Paragraph(html.escape(str(m.get("frequency", ""))), cell_text_style),
                    Paragraph(html.escape(str(m.get("duration", ""))), cell_text_style),
                    Paragraph(html.escape(str(m.get("notes", "") or "-")), cell_text_style),
                ])
            rx_table = Table(rx_rows, colWidths=[150, 80, 110, 80, 120])
            rx_style = [
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
                ("PADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            for r_idx in range(1, len(rx_rows)):
                bg = colors.HexColor("#FFFFFF") if r_idx % 2 == 1 else colors.HexColor("#F0FDFA")
                rx_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), bg))
            rx_table.setStyle(TableStyle(rx_style))
            elements.append(rx_table)
            elements.append(Spacer(1, 14))

    signoff_data = [
        [
            Paragraph(
                f"<b>Clinical Audit Attestation:</b><br/>"
                f"This document certifies that the above transcript represents an official record of the virtual "
                f"consultation conducted via MediQueue Connect between Dr. {doctor} and {patient}. "
                f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}.",
                signoff_style,
            )
        ]
    ]
    signoff_table = Table(signoff_data, colWidths=[540])
    signoff_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#F59E0B")),
            ("PADDING", (0, 0), (-1, -1), 8),
        ])
    )
    elements.append(signoff_table)
    elements.append(Spacer(1, 14))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR, spaceAfter=8))
    elements.append(
        Paragraph(
            "MediQueue Connect Architecture  •  Distributed Asynchronous Task Queue  •  Confidential Medical Record",
            footer_style,
        )
    )

    doc.build(elements)
    return os.path.abspath(output_path) if isinstance(output_path, (str, os.PathLike)) else "in-memory"
