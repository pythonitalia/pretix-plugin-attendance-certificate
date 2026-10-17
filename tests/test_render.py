import json
from io import BytesIO

import pytest
from django_scopes import scopes_disabled

from pretix.base.models import Question, QuestionAnswer

from pretix_attendance_certificate.render import render_certificate


def _field(content, bottom):
    return {
        "type": "textarea", "left": "20", "bottom": str(bottom), "fontsize": "14",
        "color": [0, 0, 0, 1], "fontfamily": "Open Sans", "bold": False, "italic": False,
        "width": "150", "content": content, "text": "x", "align": "left",
    }


@pytest.mark.django_db
def test_question_answers_can_be_placed_on_the_certificate(event, order, pos, layout):
    pypdf = pytest.importorskip("pypdf")
    with scopes_disabled():
        question = Question.objects.create(
            event=event, question="Course", type="S", identifier="COURSE"
        )
        question.items.add(pos.item)
        QuestionAnswer.objects.create(
            question=question, orderposition=pos, answer="Advanced Rope Techniques"
        )
        layout.layout = json.dumps(
            [_field("question_COURSE", 200), _field("attendee_name", 150)]
        )
        layout.save()
        pdf = render_certificate(position=pos, event=event, layout=layout)
    text = pypdf.PdfReader(BytesIO(pdf.read())).pages[0].extract_text()
    assert "Advanced Rope Techniques" in text
    assert "Marco Acierno" in text
