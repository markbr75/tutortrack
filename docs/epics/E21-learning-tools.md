# E21 — Learning Tools: Progress, Homework, Resources & Assessments

| | |
|---|---|
| **Phase** | Scale (Phase 3); homework and resources basics can ship in Phase 2 |
| **Depends on** | E05, E08, E09, E15, E16 |
| **Parity** | TutorBird LMS-lite (files, homework, news, lending library). **Beyond:** goals, curriculum mapping, assessments, progress reports — a reported gap in TutorBird |

## 1. Summary
Lightweight learning-management features that make tutoring outcomes visible: a resource library, homework assignment and submission, curriculum/topic tracking, goals, assessments/mock-exam scores, progress reports for parents, and a lending library.

## 2. Functional requirements

### FR-21-1 Resource library
- Org library + tutor personal libraries: files (PDF, images, audio, video), links (YouTube, Google Docs), folders, tags by subject/level/topic, visibility (staff, tutors, shared to specific students/classes).
- Share a resource to a student, job, lesson or class; students see it in the portal; track viewed/downloaded.
- Storage quotas per plan (E04).

### FR-21-2 Homework
- Assign from a lesson/report or standalone: title, instructions, attachments/resources, due date, student(s), expected time, submission type (file upload, text, link, none/mark done).
- Student/parent submits via portal; tutor reviews: mark complete, grade (scale per org: %, letter, 1–9, custom), feedback; resubmission.
- Reminders before due and when overdue (E13); homework completion stats.

### FR-21-3 Curriculum and topics
- Curriculum trees (Subject/Level → Units → Topics), seeded for major specs (e.g. GCSE Maths, KS2 English, SAT Math) and editable/importable (CSV).
- Lesson report "topics covered" picker (E09) links lessons to topics; topic mastery rating per student (not started / learning / secure / mastered).
- Coverage view per student: heatmap of topics covered and mastery.

### FR-21-4 Goals
- Student goals (target grade, exam date, custom SMART goals) with milestones and progress %; tutor updates; visible to parents; `goal.achieved` event.

### FR-21-5 Assessments
- Record assessment results: name, type (diagnostic, mock exam, quiz, school report), date, score/max, grade, notes, attachment.
- Simple built-in quizzes (Phase 3b): multiple choice/short answer, auto-marking, assigned like homework; also used for tutor subject tests (E18 FR-18-3).
- Charts of score trend over time.

### FR-21-6 Progress reports
- Periodic progress report (termly/monthly) generated from attendance, report highlights, topics, goals, assessments, homework completion; tutor adds summary comments (AI draft via E31); approval → shared to parents (portal + PDF).

### FR-21-7 Lending library
- Items (books, instruments, devices) with inventory, lend to student with due date, return tracking, overdue reminders, replacement charge (E10 ad hoc).

### FR-21-8 Whiteboard/online classroom resources
- Attach resources to online lessons and auto-share with the video integration (E22) where supported (e.g. Lessonspace space resources).

## 3. Data model
`Resource`, `ResourceFolder`, `ResourceShare`, `Homework`, `HomeworkAssignment(student)`, `HomeworkSubmission`, `GradeScale`, `Curriculum`, `CurriculumNode`, `LessonTopic`, `TopicMastery(student, node, level, updated_by)`, `Goal`, `GoalMilestone`, `Assessment`, `AssessmentResult`, `Quiz`, `QuizQuestion`, `QuizAttempt`, `ProgressReport`, `LibraryItem`, `Loan`.

## 4. Events
`resource.shared`, `homework.assigned/submitted/graded/overdue`, `goal.created/achieved`, `assessment.recorded`, `progress_report.shared`, `loan.overdue`.

## 5. Delivery plan
- [ ] **E21-T01** Resource library with sharing and portal display.
- [ ] **E21-T02** Homework assign/submit/review with reminders.
- [ ] **E21-T03** Curriculum trees (seed + CSV import), topic tagging in lesson reports, mastery.
- [ ] **E21-T04** Goals and milestones.
- [ ] **E21-T05** Assessments and trend charts.
- [ ] **E21-T06** Progress report generator and sharing.
- [ ] **E21-T07** Lending library.
- [ ] **E21-T08** (Phase 3b) Built-in quizzes.
