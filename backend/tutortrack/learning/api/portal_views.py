"""Family and student portal pages for learning (E15 pages on E21): homework (hand in,
quizzes), shared resources, goals, assessment results, topic coverage, progress reports
and library loans. Every view resolves the household first, so other families' records
are 404s."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.exceptions import FeatureDisabled, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.portal.api.views import PortalView
from tutortrack.portal.household import Household
from tutortrack.tenancy.settings_service import get_setting

from .. import selectors, services
from ..models import Homework, HomeworkAssignment, Loan
from . import serializers as s
from .views import pdf_response


class LearningPortalView(PortalView):
    def learning(self, request: Request) -> Household:
        household = self.household(request)
        if not get_setting("learning.portal_enabled"):
            raise FeatureDisabled("learning")
        if not (
            has_perm(request.user, "portal.client.learning")
            or has_perm(request.user, "portal.student.learning")
        ):
            raise PermissionDenied()
        return household

    def assignment(self, household: Household, pk: Any) -> HomeworkAssignment:
        found = selectors.household_assignments(household).filter(pk=pk).first()
        if found is None:
            raise NotFound()
        return found


class PortalSummaryView(LearningPortalView):
    @extend_schema(responses=s.PortalSummarySerializer)
    def get(self, request: Request) -> Response:
        """Counts for the portal home: homework to do, resources, goals, reports, loans."""
        return Response(
            s.PortalSummarySerializer(selectors.portal_summary(self.learning(request))).data
        )


def _quiz(assignment: HomeworkAssignment) -> dict[str, Any] | None:
    quiz = assignment.homework.quiz
    if quiz is None or assignment.homework.submission_type != Homework.SubmissionType.QUIZ:
        return None
    return {
        "id": quiz.pk,
        "title": quiz.title,
        "time_limit_minutes": quiz.time_limit_minutes,
        "questions": [
            {
                "id": q.pk,
                "kind": q.kind,
                "prompt": q.prompt,
                "choices": q.choices,
                "points": q.points,
            }
            for q in quiz.questions.all()
        ],
    }


def homework_card(assignment: HomeworkAssignment) -> dict[str, Any]:
    homework = assignment.homework
    attempt = assignment.quiz_attempts.order_by("-submitted_at").first()
    late_ok = bool(get_setting("learning.late_submissions"))
    return {
        "id": assignment.pk,
        "title": homework.title,
        "instructions": homework.instructions,
        "student": assignment.student_id,
        "student_name": assignment.student.full_name,
        "tutor_name": homework.set_by.full_name if homework.set_by else "",
        "due_at": assignment.due_at,
        "status": assignment.status,
        "overdue": assignment.is_open and assignment.due_at < now(),
        "can_submit": assignment.is_open
        and homework.status == Homework.Status.ACTIVE
        and (late_ok or assignment.due_at >= now()),
        "submission_type": homework.submission_type,
        "expected_minutes": homework.expected_minutes,
        "is_late": assignment.is_late,
        "grade": assignment.grade,
        "feedback": assignment.feedback,
        "resources": [
            {"id": r.pk, "title": r.title, "media_type": r.media_type}
            for r in homework.resources.filter(archived_at__isnull=True)
        ],
        "attachments": s.file_refs(homework.attachments.all()),
        "submissions": list(assignment.submissions.prefetch_related("files")),
        "quiz": _quiz(assignment) if assignment.is_open else None,
        "quiz_result": (
            {"percent": attempt.percent, "passed": attempt.passed, "marks": attempt.marks}
            if attempt is not None
            else None
        ),
    }


class PortalHomeworkView(LearningPortalView):
    @extend_schema(
        responses=s.PortalHomeworkSerializer(many=True),
        parameters=[
            OpenApiParameter("open", OpenApiTypes.BOOL, description="Only work still to do"),
            OpenApiParameter("student", OpenApiTypes.UUID),
        ],
    )
    def get(self, request: Request) -> Response:
        household = self.learning(request)
        qs = selectors.household_assignments(household)
        if request.query_params.get("open") in {"1", "true"}:
            qs = qs.filter(status__in=HomeworkAssignment.OPEN)
        student = request.query_params.get("student")
        if student:
            qs = qs.filter(student_id=student)
        rows = [homework_card(a) for a in qs[:200]]
        return Response(s.PortalHomeworkSerializer(rows, many=True).data)


class PortalHomeworkDetailView(LearningPortalView):
    @extend_schema(responses=s.PortalHomeworkSerializer)
    def get(self, request: Request, assignment_id: Any) -> Response:
        assignment = self.assignment(self.learning(request), assignment_id)
        return Response(s.PortalHomeworkSerializer(homework_card(assignment)).data)


class PortalHomeworkSubmitView(LearningPortalView):
    @extend_schema(request=s.PortalSubmitSerializer, responses={201: s.PortalHomeworkSerializer})
    def post(self, request: Request, assignment_id: Any) -> Response:
        """Hand in homework: text, a link, uploaded files (``/files/uploads`` first), the
        quiz answers (``{question_id: choice ids | text}``), or nothing for "done"."""
        household = self.learning(request)
        assignment = self.assignment(household, assignment_id)
        payload = s.PortalSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        files = list(data.get("files", []))
        if any(f.uploaded_by_id != request.user.pk for f in files):
            raise PermissionDenied()  # only files this person uploaded
        services.submit_homework(
            assignment,
            user=request.user,
            body=data.get("body", ""),
            link=data.get("link", ""),
            files=files,
            quiz_answers=data.get("quiz_answers"),
        )
        fresh = self.assignment(household, assignment_id)
        return Response(
            s.PortalHomeworkSerializer(homework_card(fresh)).data, status=status.HTTP_201_CREATED
        )


class PortalResourcesView(LearningPortalView):
    @extend_schema(responses=s.PortalResourceSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Resources shared with the household's students (directly, their jobs, lessons
        and classes), newest share first."""
        household = self.learning(request)
        latest: dict[str, Any] = {}
        for share in (
            selectors.household_shares(household)
            .select_related("resource__subject")
            .order_by("-created_at")[:500]
        ):
            latest.setdefault(str(share.resource_id), share)
        rows = [
            {
                "id": share.resource.pk,
                "title": share.resource.title,
                "description": share.resource.description,
                "kind": share.resource.kind,
                "media_type": share.resource.media_type,
                "subject": share.resource.subject.name if share.resource.subject else "",
                "message": share.message,
                "shared_at": share.created_at,
            }
            for share in latest.values()
        ]
        return Response(s.PortalResourceSerializer(rows, many=True).data)


class PortalResourceOpenView(LearningPortalView):
    @extend_schema(request=None, responses=s.OpenResourceSerializer)
    def post(self, request: Request, resource_id: Any) -> Response:
        """Open a shared resource (download link or the link itself); the view is
        recorded for the tutor."""
        household = self.learning(request)
        resource = selectors.household_resources(household).filter(pk=resource_id).first()
        if resource is None:
            raise NotFound()
        student = household.students[0] if household.role == "student" else None
        return Response(services.open_resource(resource, request.user, student=student))


class PortalGoalsView(LearningPortalView):
    @extend_schema(responses=s.GoalSerializer(many=True))
    def get(self, request: Request) -> Response:
        goals = selectors.household_goals(self.learning(request))
        return Response(s.GoalSerializer(goals, many=True).data)


class PortalResultsView(LearningPortalView):
    @extend_schema(responses=s.PortalResultSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Assessment results, oldest first (for the trend chart)."""
        rows = [
            {
                "id": r.pk,
                "name": r.assessment.name,
                "kind": r.assessment.kind,
                "subject": r.assessment.subject.name if r.assessment.subject else "",
                "student": r.student_id,
                "student_name": r.student.full_name,
                "date": r.taken_on,
                "score": r.score,
                "max_score": r.max_score,
                "percent": r.percent,
                "grade": r.grade,
            }
            for r in selectors.household_results(self.learning(request)).order_by("taken_on")
        ]
        return Response(s.PortalResultSerializer(rows, many=True).data)


class PortalCoverageView(LearningPortalView):
    @extend_schema(responses=s.CoverageSerializer(many=True))
    def get(self, request: Request, student_id: Any) -> Response:
        household = self.learning(request)
        student = next((x for x in household.students if str(x.pk) == str(student_id)), None)
        if student is None:
            raise NotFound()
        return Response(s.CoverageSerializer(selectors.coverage(student), many=True).data)


def _report_row(report: Any) -> dict[str, Any]:
    return {
        "id": report.pk,
        "title": report.title,
        "student": report.student_id,
        "student_name": report.student.full_name,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "summary": report.summary,
        "snapshot": report.snapshot,
        "shared_at": report.shared_at,
    }


class PortalReportsView(LearningPortalView):
    @extend_schema(responses=s.PortalProgressSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = [_report_row(r) for r in selectors.household_reports(self.learning(request))]
        return Response(s.PortalProgressSerializer(rows, many=True).data)


class PortalReportPdfView(LearningPortalView):
    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request, report_id: Any) -> HttpResponse:
        report = selectors.household_reports(self.learning(request)).filter(pk=report_id).first()
        if report is None:
            raise NotFound()
        return pdf_response(report)


class PortalLoansView(LearningPortalView):
    @extend_schema(responses=s.PortalLoanSerializer(many=True))
    def get(self, request: Request) -> Response:
        today = services.org_today()
        rows = [
            {
                "id": loan.pk,
                "item": loan.item.name,
                "student_name": loan.student.full_name,
                "status": loan.status,
                "lent_on": loan.lent_on,
                "due_date": loan.due_date,
                "returned_on": loan.returned_on,
                "is_overdue": loan.status == Loan.Status.OUT and loan.due_date < today,
            }
            for loan in selectors.household_loans(self.learning(request)).order_by("-lent_on")
        ]
        return Response(s.PortalLoanSerializer(rows, many=True).data)
