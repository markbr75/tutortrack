"""Permission codenames owned by learning (E21). Tutors hold ``learning.*:own`` (their
students, their own resources and quizzes) except the ones their role denies."""

PERMISSIONS = {
    "learning.resource.view": "See the resource library",
    "learning.resource.manage": "Add, change and archive resources and folders",
    "learning.resource.share": "Share resources with students, jobs, lessons and classes",
    "learning.homework.view": "See homework and submissions",
    "learning.homework.manage": "Set, change and cancel homework",
    "learning.homework.review": "Review, grade and return homework",
    "learning.curriculum.view": "See curricula and topic coverage",
    "learning.curriculum.manage": "Create, import and edit curricula",
    "learning.mastery.edit": "Tag lesson topics and set students' topic mastery",
    "learning.goal.view": "See student goals",
    "learning.goal.manage": "Create and update student goals and milestones",
    "learning.assessment.view": "See assessments and results",
    "learning.assessment.manage": "Record assessments and results",
    "learning.progress.view": "See progress reports",
    "learning.progress.write": "Generate and write progress reports",
    "learning.progress.approve": "Approve progress reports and share them with families",
    "learning.library.view": "See the lending library and loans",
    "learning.library.manage": "Manage library items, lend and take returns",
    "learning.library.charge": "Charge families for lost library items",
    "learning.quiz.view": "See quizzes and attempts",
    "learning.quiz.manage": "Create and edit quizzes",
    "portal.client.learning": "Client portal: the household's homework, resources and progress",
    "portal.student.learning": "Student portal: own homework, resources and progress",
}
