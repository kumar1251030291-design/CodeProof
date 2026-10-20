"""In-memory, escaped PDF rendering for candidate and evaluator result reports."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import re
from threading import Lock
from typing import Iterable
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Assessment, AssessmentAttempt, AttemptResponse, Question, UserProfile

_INK = colors.HexColor("#242335")
_MUTED = colors.HexColor("#626273")
_PURPLE = colors.HexColor("#7054bd")
_PALE = colors.HexColor("#f0eef8")
_BORDER = colors.HexColor("#d9d7e1")
_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"
_FONT_LOCK = Lock()


def _register_fonts() -> None:
    global _FONT, _BOLD
    with _FONT_LOCK:
        fonts_dir = Path(reportlab.__file__).parent / "fonts"
        regular = fonts_dir / "Vera.ttf"
        bold = fonts_dir / "VeraBd.ttf"
        if regular.is_file() and bold.is_file():
            if "CodeProofVera" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("CodeProofVera", str(regular)))
            if "CodeProofVera-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("CodeProofVera-Bold", str(bold)))
            _FONT, _BOLD = "CodeProofVera", "CodeProofVera-Bold"


def _plain(value: object, *, limit: int = 25000) -> str:
    """Convert untrusted text to escaped paragraph content with a report-size cap."""
    text = str(value or "")
    text = "".join(char for char in text if char in "\n\r\t" or ord(char) >= 32)
    if len(text) > limit:
        text = text[:limit] + "\n[Content shortened in this report]"
    return escape(text).replace("\r\n", "\n").replace("\n", "<br/> ") or "—"


def _date(value: datetime | None) -> str:
    if value is None:
        return "Not available"
    timestamp = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("CodeProofTitle", parent=base["Title"], fontName=_BOLD, fontSize=20, leading=25, textColor=_INK, alignment=TA_LEFT, spaceAfter=5),
        "subtitle": ParagraphStyle("CodeProofSubtitle", parent=base["Normal"], fontName=_FONT, fontSize=9, leading=13, textColor=_MUTED, spaceAfter=12),
        "heading": ParagraphStyle("CodeProofHeading", parent=base["Heading2"], fontName=_BOLD, fontSize=12, leading=16, textColor=_INK, spaceBefore=13, spaceAfter=7),
        "question": ParagraphStyle("CodeProofQuestion", parent=base["Heading3"], fontName=_BOLD, fontSize=10, leading=14, textColor=_PURPLE, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("CodeProofBody", parent=base["BodyText"], fontName=_FONT, fontSize=8.5, leading=12, textColor=_INK, splitLongWords=1),
        "small": ParagraphStyle("CodeProofSmall", parent=base["BodyText"], fontName=_FONT, fontSize=7.5, leading=10, textColor=_MUTED),
        "label": ParagraphStyle("CodeProofLabel", parent=base["BodyText"], fontName=_BOLD, fontSize=7, leading=9, textColor=_MUTED),
    }


def _p(value: object, style: ParagraphStyle, *, limit: int = 25000) -> Paragraph:
    return Paragraph(_plain(value, limit=limit), style)


def _metadata_table(rows: Iterable[tuple[str, object]], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[_p(label, styles["label"]), _p(value, styles["body"])] for label, value in rows]
    table = Table(data, colWidths=[1.35 * inch, 5.55 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (0, -1), _PALE),
        ("GRID", (0, 0), (-1, -1), 0.45, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _score_table(rows: list[tuple[str, object]], styles: dict[str, ParagraphStyle]) -> Table:
    cells = [[_p(label, styles["label"]), _p(value, styles["body"])] for label, value in rows]
    table = Table(cells, colWidths=[1.35 * inch, 5.55 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#faf9fd")),
        ("BOX", (0, 0), (-1, -1), 0.8, _PURPLE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _build(story: list[object], document_title: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=0.8 * inch, leftMargin=0.8 * inch,
        topMargin=0.7 * inch, bottomMargin=0.65 * inch, title=document_title,
        author="CodeProof", pageCompression=0,
    )

    def footer(canvas: object, _doc: object) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_BORDER)
        canvas.line(0.8 * inch, 0.48 * inch, 7.7 * inch, 0.48 * inch)
        canvas.setFont(_FONT, 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(0.8 * inch, 0.32 * inch, "CodeProof · Assessment report")
        canvas.drawRightString(7.7 * inch, 0.32 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def candidate_attempt_pdf(
    assessment: Assessment,
    attempt: AssessmentAttempt,
    profile: UserProfile,
    identity_email: str | None,
    responses: list[AttemptResponse],
    *,
    results_visible: bool,
) -> bytes:
    styles = _styles()
    story: list[object] = [
        _p(assessment.title, styles["title"], limit=500),
        _p("Candidate attempt report", styles["subtitle"]),
        _metadata_table([
            ("Candidate", profile.display_name or identity_email or str(profile.id)),
            ("Assessment", assessment.title),
            ("Attempt", f"{attempt.attempt_number}"),
            ("Status", attempt.status.replace("_", " ").title()),
            ("Started", _date(attempt.started_at)),
            ("Submitted", _date(attempt.submitted_at)),
        ], styles),
        Spacer(1, 12),
    ]
    if results_visible:
        story.append(_p("Final result", styles["heading"]))
        story.append(_score_table([
            ("Final score", f"{attempt.final_score} / {attempt.max_score}"),
            ("Review status", attempt.review_status.replace("_", " ").title()),
        ], styles))
        response_by_question = {response.question_id: response for response in responses}
        if assessment.questions:
            story.append(_p("Question-level automatic results", styles["heading"]))
            for index, question in enumerate(assessment.questions, 1):
                response = response_by_question.get(question.id)
                score = "Not available" if response is None or response.score is None else f"{response.score} / {question.points} points"
                story.append(_p(f"Question {index}: {question.title}", styles["question"]))
                story.append(_p(f"Automatic result: {score}", styles["body"]))
    elif attempt.status == "in_progress":
        story.append(Spacer(1, 8))
        story.append(_p("This attempt is still in progress. It is not a finalized result; no score is included.", styles["body"]))
    elif attempt.review_status == "pending":
        story.append(Spacer(1, 8))
        story.append(_p("Submitted — pending manual review. No final score or question-level results are included.", styles["body"]))
    elif attempt.status != "submitted":
        story.append(Spacer(1, 8))
        story.append(_p("This attempt is not a finalized submission. No score is included.", styles["body"]))
    else:
        story.append(Spacer(1, 8))
        story.append(_p("Results are not yet available under this assessment's result visibility policy. No score or question-level results are included.", styles["body"]))
    return _build(story, f"Candidate attempt report - {assessment.title}")


def evaluator_attempt_pdf(
    assessment: Assessment,
    attempt: AssessmentAttempt,
    candidate: UserProfile | None,
    responses: list[AttemptResponse],
) -> bytes:
    styles = _styles()
    candidate_label = candidate.display_name if candidate and candidate.display_name else str(attempt.candidate_id)
    story: list[object] = [
        _p(assessment.title, styles["title"], limit=500),
        _p("Evaluator submission report", styles["subtitle"]),
        _metadata_table([
            ("Candidate", candidate_label),
            ("Candidate ID", str(attempt.candidate_id)),
            ("Assessment", assessment.title),
            ("Attempt", str(attempt.attempt_number)),
            ("Status", attempt.status.replace("_", " ").title()),
            ("Started", _date(attempt.started_at)),
            ("Submitted", _date(attempt.submitted_at)),
        ], styles),
        _p("Score summary", styles["heading"]),
        _score_table([
            ("Automatic score", "Not available" if attempt.score is None else f"{attempt.score} / {attempt.max_score}"),
            ("Manual score", "Pending" if attempt.manual_score is None else str(attempt.manual_score)),
            ("Final score", "Pending" if attempt.final_score is None else f"{attempt.final_score} / {attempt.max_score}"),
            ("Review status", "Pending manual review" if attempt.review_status == "pending" else attempt.review_status.replace("_", " ").title()),
        ], styles),
        _p("Question-level review", styles["heading"]),
    ]
    response_by_question = {response.question_id: response for response in responses}
    for index, question in enumerate(assessment.questions, 1):
        response = response_by_question.get(question.id)
        if question.question_type == "explanation" and (response is None or response.manual_score is None):
            review_label = "Awaiting manual review"
        elif response and response.manual_score is not None:
            review_label = f"Manually graded: {response.manual_score} / {question.points} points"
        else:
            automatic = "Not available" if response is None or response.score is None else f"{response.score} / {question.points} points"
            review_label = f"Automatic result: {automatic}"
        content = [
            _p(f"Question {index}: {question.title}", styles["question"]),
            _p(f"Type: {question.question_type.replace('-', ' ')} · Maximum points: {question.points}", styles["small"]),
            _p(f"Prompt: {question.prompt}", styles["body"]),
            _p(review_label, styles["body"]),
        ]
        if response:
            content.extend([
                Spacer(1, 4),
                _p("Candidate answer", styles["label"]),
                _p(response.response_text, styles["body"], limit=25000),
            ])
            if response.programming_language:
                content.append(_p(f"Language: {response.programming_language}", styles["small"]))
            if response.manual_feedback:
                content.extend([_p("Evaluator feedback", styles["label"]), _p(response.manual_feedback, styles["body"], limit=10000)])
            if response.execution_status and question.question_type in {"programming", "debugging"}:
                cases = "" if response.passed_test_cases is None or response.total_test_cases is None else f" · {response.passed_test_cases}/{response.total_test_cases} cases passed"
                content.append(_p(f"Execution status: {response.execution_status.replace('_', ' ')}{cases}", styles["small"]))
        story.append(KeepTogether(content))
        story.append(HRFlowable(width="100%", thickness=0.4, color=_BORDER, spaceBefore=4, spaceAfter=4))
    return _build(story, f"Evaluator submission report - {assessment.title}")


def safe_report_filename(prefix: str, identifier: object) -> str:
    """Use only a fixed prefix and normalized ID in Content-Disposition."""
    suffix = re.sub(r"[^A-Za-z0-9_-]", "", str(identifier))[:12] or "report"
    return f"codeproof-{prefix}-{suffix}.pdf"
