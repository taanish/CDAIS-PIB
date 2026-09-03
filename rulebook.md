# AI Deployment Rulebook (Stage 3)

Plain-English rules for sorting each AI-mentioning release into a type, and
pulling out the real AI systems. Written to be applied by a person or a model;
either way, every call is backed by an evidence sentence so it can be checked.

---

## Step 0 — Is this release actually about AI?

- If the AI word is a **false match** — "artificial insemination", "automated
  machinery", "smart connectivity", a person named after a keyword — → **Not AI**. Stop.
- If AI appears **only as one item in a list** of buzzwords ("semiconductors,
  robotics, AI, space") and nothing more is said about it → **Not AI**. Stop.
- Otherwise, continue.

## Step 1 — What type is it?

Pick the bucket that best describes what the release is *about*.

- **AI system** — the release is reporting on a specific AI tool the government
  has, is testing, is buying, or has announced. (Carries a stage — see below.)
- **Research** — AI being built or studied in a lab; not out in the world yet.
- **Funding** — the government gives money or signs an MoU so *someone else*
  builds or runs AI. The government is not the operator.
- **Policy** — a plan, strategy, guideline, or study about AI. No specific system.
- **Training** — courses, skilling, hackathons, fellowships.
- **Talk** — a speech, summit, conference, webinar, or review that only mentions AI.

If a release fits more than one, and one is a specific system the release is
genuinely reporting on, label it **AI system**. Otherwise use the best fit.

## The AI system stages

- **Announced** — a specific system they say they'll build or deploy. Not started.
- **Buying** — a tender is out or a contract is signed. Not running yet.
- **Trial** — being tested in a limited way.
- **Working** — running now.

## What counts as a "system" to log

- A named or clearly-claimed AI tool the government runs, tests, buys, or announces.
- Log it **even if the release doesn't explain what it does.** Record the use
  case if given; if not, write "not described" and set the use-case flag to no.

## The reporting rule (important — added after the tests)

- Only log a system when the release is actually **reporting on it** — announcing,
  launching, updating, or buying it.
- Do **not** log a system that is only **name-dropped in passing** as an example
  of what already exists (e.g. a minister listing BHASHINI in a G7 speech). That
  logs no system. This stops the same system being counted from every speech.
- BUT: if the government is **announcing or reporting its OWN system** — even
  inside a speech — **do** log it (e.g. "the Home Ministry is building software
  using AI"). Announcing your own new system is reporting; citing someone's
  existing one as an example is not.
- A release's **type and its system records are separate.** A **Talk** release
  (a speech) can still hand you a real system record when the government reports
  its own AI work inside it. Label the release by what it is *about*; pull the
  system records separately.

## What makes a deployment (the unit)

- A deployment = **one government operator + one AI technology**.
- **Government operator = a deployment**, no matter who built the technology.
- Government **funding** a private party that runs it itself = **not** a
  government deployment (that's Funding).
- If a release has several operator/technology pairs → **one record each**.

## Edge rulings

- Signed contract, nothing running yet → **Buying** (not Working).
- Private company built it, government runs it → **Working** (government operates).
- Government only funds or enables; a private party runs it → **Funding**.
- Automation with no learning (a workflow, a form-filling portal) → **Not AI**.
- Drones, cameras, satellites with no AI analysis described → **Not AI**.
- "Autonomous body / institute" (an organisation) → not an AI signal; ignore.

## What we record

For **every** release: relid, URL, date, title, type, and the one sentence that
decided the type.

For each **system** (AI-system releases only): system name, government body
(operator), area, stage, use case (or "not described" + flag), and the exact
evidence sentence.

## Area list

policing/security, welfare/benefits, health, agriculture, transport, education,
defence, tax/finance, environment/weather, governance/admin, justice/legal, other.
