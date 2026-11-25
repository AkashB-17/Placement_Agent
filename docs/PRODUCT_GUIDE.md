# Placement Portal: Product Guide

*An explainable shortlisting and staged auto-apply system for campus placements.*

This guide explains what the product does, who it is for, how each person uses it, and why its decisions can be trusted. No programming knowledge is needed. For how the code is organised, see [CONTRIBUTOR_GUIDE.md](CONTRIBUTOR_GUIDE.md).

---

## 1. The problem

Every placement season, a college placement cell receives dozens of job descriptions (JDs) and has hundreds of students. For each job, someone has to answer two questions:

1. **Who is allowed to apply?** Each job has rules: minimum CGPA, no active backlogs, certain branches only, a specific graduating batch, and the college's own policy (for example, already-placed students may not apply again).
2. **Who is a good fit?** Among the eligible students, whose resume actually shows the skills the job asks for?

Doing this by hand is slow and error-prone. Doing it with a "black-box AI score" is fast but impossible to defend: when a student asks *"why was I rejected?"* or *"why is my score 45?"*, there is no answer.

## 2. What the product does

The officer uploads the college placement policy once and a job description per company. The system then:

- **Checks eligibility with fixed rules.** CGPA, active backlogs, branch, batch and the placed-student rule are checked by ordinary code, the same way every time. AI is never used for this decision.
- **Explains every rejection.** Each failed rule is listed ("CGPA 6.8, needs 7.0, from the policy"), together with the exact clause of the policy or JD it comes from.
- **Scores only eligible students**, from their full resume, against the skills the JD asks for.
- **Shows the evidence behind every score.** For each skill it lists whether it was found and the exact sentence from the resume that proves it. The score itself is a formula over those matches, not an AI opinion.
- **Can apply on students' behalf, safely** ("staged auto-apply"): students opt in, the system prepares applications for the jobs they qualify for, tells them, and gives them time to withdraw before anything is sent.

> **What this product is not.** It is a *deterministic workflow with AI steps*: read the documents, filter, score, apply at a threshold. AI reads documents and finds evidence; code makes every decision. It is not an autonomous "agent" making choices on its own.

## 3. Who uses it

| Role | Who | What they can do |
|---|---|---|
| **Admin** | Head of the placement cell / system owner | Everything an officer can, plus invite people and change roles |
| **Placement officer** | Placement cell staff | Upload the policy, JDs and students; rank candidates; run auto-apply; track applications |
| **Recruiter** | Company HR | Upload JDs for their company; see applications to *their* jobs once they are sent |
| **Student** | Final-year students | See their own record; check their fit for each job; opt in to auto-apply; withdraw applications |

Students create their own account (**Create an account** on the sign-in page) with the email the placement cell has on record, and confirm it from the link they are emailed. Every new account is a **student**. Officer, recruiter and admin roles can only be granted by an admin, so nobody can promote themselves; invited staff choose their password from the link in their invitation email. Anyone can reset a forgotten password with **Forgot password?**.

## 4. A tour of the product

### 4.1 Placement officer

**Upload** (left menu → Upload)
- *Placement policy*: paste the text or drop a PDF/TXT. The system reads out the rules (minimum CGPA, maximum backlogs, branches, batches, placed-student rule).
- *Job description*: same, for each company. The system reads the company, role, required and preferred skills, any stricter CGPA, branch and batch rules, CTC and deadline.
- *Student*: name, login email, branch, batch, CGPA, backlogs and placed status, the academic record the placement cell holds. The CV is optional here: **students upload their own CV** after signing in. Re-adding a student updates their record and never wipes their CV.

After an upload you see what was read. If the AI "found" a rule the document never states (for example it mistook the application deadline for a batch year), the system drops that rule and shows a **warning** instead of silently enforcing something that isn't there.

**Rank candidates** (left menu → Rank candidates)
1. Choose the placement policy (top right) and click a job card.
2. Four summary tiles show: how many are eligible, how many are not, how many qualify for auto-apply, and the top score.
3. Eligible students are ranked by score. Each card shows a score ring and, under **Details**:
   - required and preferred skills, matched (green) or missing (red/amber);
   - **evidence**: the exact resume sentence for each matched skill.
4. Ineligible students show each failed rule, and under **Details** the policy or JD clause it comes from.
5. **Re-run** re-checks eligibility instantly using stored scores. **Re-score with AI** asks the AI again (only needed if you suspect a stale score; results are normally identical).

**Run auto-apply** (on the Rank page, under the summary tiles)
- One click, then **Confirm**. The system applies for every student who opted in and qualifies (see §6), and lists who was applied and *why each other student was not*.

**Students** (left menu → Students)
- Searchable list of all students. Click a row for their parsed skills, projects and a link to open their resume file (the link works for 60 seconds).

**Applications** (left menu → Applications)
- Every auto-apply application with its status: **Pending** (with a countdown to when it is sent), **Sent to company**, or **Withdrawn**. Filter by job.

### 4.2 Student

Students get their own layout: a top bar with a **notification bell** (unread count; "We applied to X for you, it will be sent on…", "Your application has been sent", "You withdrew…") and an icon rail with four pages (a slide-out menu on phones).
- **Jobs** (home page): a job board. The list shows every job with its company, CTC, when it was posted, how long until it closes (red in the last 24 hours) and a status: *Eligible*, *Not eligible*, *Applied*, *Sent to company*, *Withdrawn* or *Applications closed*. Filter by status, sort by newest or closing soon, search, and switch between *All jobs* and *Applied jobs*. Selecting a job opens its detail: the application (with countdown and **Withdraw**) if one exists, and three tabs: **Job description**, **Eligibility criteria** (each rule the student fails, with their value against the requirement and whether the rule came from the policy or the job), and **My match** (score, matched/missing skills and evidence; needs a CV). Eligibility on the board is the fixed rule check, so the board loads without any AI call.
  - **Apply** sits under the job's status. It is greyed out, with the reason, when the student isn't eligible, applications are closed or no CV is uploaded. After a confirmation it goes through the same steps as auto-apply (rules checked by code, CV and score snapshot, withdraw window, then sent), without the score bar: the student chose the job. A withdrawn application can't be re-sent.
  - **Improve your CV for this job** (in My match, for an eligible student): lists the job's skills the CV doesn't show, worked out by code from the score. **Suggest changes** asks the AI for one suggestion per gap. Where the CV already describes related work, the tip quotes that line (checked to really be in the CV) and suggests how to make the skill visible: *You may already have this*. Otherwise it suggests a concrete way to gain it: *Skill to build*. Tips never suggest claiming skills the student hasn't used, and the CV is never edited for them.
- **Applications**: every application, whether the student made it or auto-apply did, with a live countdown and a **Withdraw** button while it is pending.
- **Profile & CV**: branch, batch, CGPA, backlogs (set by the placement cell, not editable), the skills found in their CV, and **Your CV**: upload or replace it (PDF/TXT) and open the current one. Until a CV is uploaded the student can see jobs and eligibility but has no score, and auto-apply skips them. Applications already made keep the CV version they were scored on.
- **Auto-apply**: on/off switch, a minimum score (can only be raised above the college threshold), and companies to never apply to.

A student only ever sees their own record. Their account is linked to their record by the email the placement cell entered.

### 4.3 Recruiter

- **Upload** JDs for their company (they cannot edit another recruiter's JD).
- **Applications**: only applications to *their own* jobs, and only once the student's withdraw window has closed and the application has been sent. Pending or withdrawn applications are never visible to recruiters. They can open the resume *as it was when the student applied*.
- Each application shows the match score, the required skills the CV shows (green) and lacks (red), and **Why they stand out**: short factual lines such as "Shows 3 of 4 required skills in their CV: Python, SQL, FastAPI", "CGPA 8.6, 1.6 above the required 7" and "No active backlogs". These are written by code, not AI, from the verified score and the academic record the eligibility rules used, and saved when the application is made.

### 4.4 Admin

- **Users & roles**: see every account and its role; change a role; invite someone by email with a role. Admins cannot remove their own admin role, which prevents an accidental lock-out.

## 5. How decisions are made

### 5.1 Eligibility: fixed rules, every failure reported

| Rule | Comes from | Passes when |
|---|---|---|
| Minimum CGPA | Policy, or a stricter JD cut-off | Student CGPA ≥ the **stricter** of the two |
| Active backlogs | Policy | Backlogs ≤ the allowed maximum |
| Branch | Policy and/or JD | Student's branch is in the allowed list |
| Batch | Policy and/or JD | Student's graduation year is in the allowed list |
| Placed students | Policy | Placed students are blocked only if the policy says so |

- A rule the documents don't state is **not enforced**.
- Branch names are understood in their common forms: "Computer Science & Engineering", "CSE" and "B.Tech CSE" are the same; "CSE/IT" means both; "all branches" means no restriction; "circuit branches" means the computer and electronics family.
- Batches are reduced to the graduation year: "2023-27", "Class of 2027" and "graduating in 2027" all mean **2027**.
- **Every** failed rule is reported, not just the first one. If both the policy and the JD exclude a branch, both are shown.

### 5.2 The score: a formula over verified evidence

For each skill in the JD, the AI is asked one narrow question: *is this skill evidenced in the resume, and which sentence shows it?* The code then checks the answer before trusting it:

1. **The quote must really be in the resume** (ignoring spacing, line breaks and capital letters). An invented quote is rejected.
2. **The quote must mention the skill.** A real sentence like "Python developer" is not accepted as evidence for Rust.
3. **The JD decides the skill list, not the AI.** A skill the AI skips or renames counts as missing, so the AI can never raise a score by leaving things out.

Only then is the score computed:

> **Score = 100 × (0.75 × share of required skills matched + 0.25 × share of preferred skills matched)**
>
> If the JD lists no preferred skills, required skills count for 100%. If it lists no required skills, there is no score.

Because the formula is fixed and every matched skill comes with its sentence, anyone can recompute and audit a score by hand.

### 5.3 Citations: the reason behind a rejection

When a student fails a rule, the system searches the policy or JD (whichever the rule came from) for the clause that states it, and shows it. Search is only used to *explain* a decision; it never *makes* one.

## 6. Staged auto-apply

Auto-apply saves students from missing deadlines, while making sure nothing is sent behind their back.

**The rules a student must meet to be auto-applied to a job**
1. They turned auto-apply **on**.
2. They have **not** already applied to this job. A withdrawn application is never re-sent.
3. The company is **not** on their "never apply to" list.
4. They are under the policy's **limit of active applications** (if the policy sets one).
5. They are **eligible** (§5.1).
6. Their score is at least the **higher** of the college threshold (default 80) and their own minimum.

**What happens next**

```
Officer runs auto-apply
        │
        ▼
 PENDING ── student notified: "We applied to X for you; it will be sent on <date>"
        │
        ├── student clicks Withdraw before the send time ──▶ WITHDRAWN (final, never re-sent)
        │
        └── send time arrives ──────────────────────────────▶ SENT to company (student notified)
```

- **Send time** = 24 hours after the application is created, or 6 hours before the JD's deadline, **whichever comes first**.
- If the deadline has passed, or less than an hour would be left to withdraw, the run is refused with a clear message.
- Each application keeps a snapshot of **the resume as it was scored** and **the score with its evidence**. If the student later uploads a new resume, what the company receives does not change.
- Recruiters see an application only after it is **sent**.
- A student can also **apply themselves** from the job board. That application follows the same path (pending, withdraw window, sent), without the score bar and the "never apply to" list.

## 7. Trust, privacy and security

- **Sign-in** is handled by Supabase Auth. Every request to the server carries a signed token that the server verifies.
- **Roles are stored on the server**, never taken from anything a user can edit. Only admins grant privileged roles.
- **Every page and every server endpoint checks the role.** Hiding a button is only a convenience; the server refuses the request anyway.
- **Row-level security** in the database means even direct database access only shows a user the rows they are allowed to see (a student sees only their own record and applications).
- **Resumes are stored in a private bucket.** They are opened only through links that expire after 60 seconds.
- **Resume versions are immutable.** Each upload is stored under a new name derived from its content, so a sent application always points to the exact file that was scored.
- **Secrets** (API keys, database password) live only on the server and are never sent to the browser.

## 8. Honest limits

- **Paraphrased skills can be missed.** The "quote must mention the skill" check looks for the skill's words. "Built RESTful services" may not count as *API design*. This errs towards a lower score rather than a wrongly high one, which is the safer mistake for auto-apply.
- **Soft skills score poorly.** "Client communication" or "negotiation" are hard to prove with a quote, so JDs built mostly on soft skills produce low scores.
- **Some PDFs extract badly.** PDFs with unusual fonts can turn "ti" into odd characters, and scanned PDFs have no text at all. Uploading a text-based PDF or a .txt file avoids this.
- **Notifications are in-app only.** Account emails (confirm sign-up, reset password, invitation) are sent by Supabase; its built-in mail service is rate-limited, so a real deployment should configure its own SMTP server in Supabase.
- **"Sent" means visible to the recruiter in this system.** There is no integration with external job portals.
- **The free server sleeps.** After 15 idle minutes the first request takes about a minute while the server wakes up. Pending applications are still sent on time: sending also happens whenever anyone opens the applications.

## 9. Frequently asked questions

**Can the AI reject a student?**
No. Eligibility is decided only by fixed rules in code. The AI reads documents into rules and looks for skill evidence; the code checks and decides.

**Will the same student get the same score tomorrow?**
Yes. The verified result is stored the first time a resume is scored against a JD, and every later ranking reuses it, so scores do not drift and re-ranking is instant. (The AI also runs at its most consistent setting, but the stored result is what guarantees repeatability.) A new resume or a changed JD produces a new score.

**Why was a rule from the JD ignored?**
Probably because the JD did not actually state it. The system drops rules it cannot find in the document and shows a warning at upload time.

**Can a student be auto-applied without knowing?**
No. They must opt in, they are notified immediately, and they have until the send time to withdraw.

**What if a company's deadline is tomorrow?**
The send time moves earlier (6 hours before the deadline). If less than an hour would be left to withdraw, auto-apply refuses to run for that job.

## 10. Glossary

| Term | Meaning |
|---|---|
| **JD** | Job description |
| **Policy** | The college's placement rules, uploaded once |
| **Eligible** | Passes every stated rule |
| **Evidence** | The exact resume sentence that proves a skill |
| **Threshold** | Minimum score for auto-apply (default 80) |
| **Pending / Sent / Withdrawn** | The three states of an auto-apply application |
| **Withdraw window** | Time between an application being created and being sent |
| **Citation** | The policy or JD clause behind a failed rule |
| **Batch** | Graduation year, e.g. 2027 |
