"""Tiny server-side translation helper — English and German only,
matching the frontend's two supported languages (see household/frontend/
js/i18n.js). Used for two things, each with a different "whose language"
rule:

- A notification's title/body (crud._notify call sites) renders in its
  RECIPIENT's own `HouseholdUser.preferred_language` — each person reads
  their own inbox in their own language.
- A PDF report (reports.py) renders in the household's
  `HouseholdSettings.default_language` instead — a report is one shared
  document, not per-viewer, so it can't follow each admin's own
  preference the way a notification follows its one recipient.

Deliberately NOT used for `ValueError`/`HTTPException` `detail` messages
(known gap — see PROJECT_STATE.md) — those still only ever reach the UI
as English toasts. Translating them needs real error codes, not just a
string lookup, which is a bigger change than this round's scope.

Not a general-purpose i18n framework — just a flat key -> {en, de}
dict and `str.format`-style substitution, sized for the handful of
message shapes this service actually sends."""

from typing import Literal

Lang = Literal["en", "de"]

_STRINGS: dict[str, dict[Lang, str]] = {
    "scheduled_task.title": {
        "en": "New scheduled task",
        "de": "Neue geplante Aufgabe",
    },
    "scheduled_task.body": {
        "en": '"{group}" created: {todo}',
        "de": '„{group}" erstellt: {todo}',
    },
    "chain_task.title": {
        "en": "New chain task",
        "de": "Neue Folgeaufgabe",
    },
    "chain_task.body": {
        "en": 'After "{parent}": {child}',
        "de": 'Nach „{parent}": {child}',
    },
    "takeover_requested.title": {
        "en": "Takeover request",
        "de": "Übernahmeanfrage",
    },
    "takeover_requested.body": {
        "en": "{requester} asked you to take over: {item}",
        "de": "{requester} hat dich gebeten, das zu übernehmen: {item}",
    },
    "takeover_responded.title": {
        "en": "Takeover request {verb}",
        "de": "Übernahmeanfrage {verb}",
    },
    "takeover_responded.body": {
        "en": "{target} {verb} your request for: {item}",
        "de": "{target} hat deine Anfrage für {item} {verb}",
    },
    "verb.accepted": {"en": "accepted", "de": "angenommen"},
    "verb.declined": {"en": "declined", "de": "abgelehnt"},
    "chore_request.title": {
        "en": "New chore request",
        "de": "Neue Aufgabenanfrage",
    },
    "chore_request.body": {
        "en": "{requester} asked you to: {todo}",
        "de": "{requester} bittet dich darum: {todo}",
    },
    "reassigned.title": {
        "en": "Task reassigned to you",
        "de": "Aufgabe dir neu zugewiesen",
    },
    "reassigned.body": {
        "en": '{admin} reassigned "{todo}" to you',
        "de": '{admin} hat dir „{todo}" neu zugewiesen',
    },
    "nudge.title": {
        "en": "Weekly reminder",
        "de": "Wöchentliche Erinnerung",
    },
    "nudge.body_with_goal": {
        "en": "You're at {points}/{goal} points this week — don't forget your chores!",
        "de": "Du stehst diese Woche bei {points}/{goal} Punkten — vergiss deine Aufgaben nicht!",
    },
    "nudge.body_no_goal": {
        "en": "Don't forget to log your points this week!",
        "de": "Vergiss nicht, deine Punkte diese Woche einzutragen!",
    },
    "report_ready.title": {
        "en": "New report generated",
        "de": "Neuer Bericht erstellt",
    },
    "report_ready.body": {
        "en": "{period} report ready: {start} – {end}",
        "de": "{period}bericht ist bereit: {start} – {end}",
    },
    "period.week": {"en": "Week", "de": "Wochen"},
    "period.month": {"en": "Month", "de": "Monats"},
    # PDF report text (reports.py) — rendered in the household's shared
    # HouseholdSettings.default_language, not a per-recipient language
    # (see module docstring above).
    "report_pdf.title.week": {
        "en": "Weekly points report",
        "de": "Wöchentlicher Punktebericht",
    },
    "report_pdf.title.month": {
        "en": "Monthly points report",
        "de": "Monatlicher Punktebericht",
    },
    "report_pdf.generated_by": {
        "en": "Generated {date}<br/>by {by}",
        "de": "Erstellt am {date}<br/>von {by}",
    },
    "report_pdf.automatic": {"en": "Automatic", "de": "Automatisch"},
    "report_pdf.empty": {
        "en": "No points were logged in this period.",
        "de": "In diesem Zeitraum wurden keine Punkte erfasst.",
    },
    "report_pdf.stat.total_points": {"en": "Total points", "de": "Gesamtpunkte"},
    "report_pdf.stat.participants": {"en": "Participants", "de": "Teilnehmer"},
    "report_pdf.stat.top_performer": {"en": "Top performer", "de": "Bestleistung"},
    "report_pdf.stat.money_per_point": {
        "en": "Money per point",
        "de": "Geld pro Punkt",
    },
    "report_pdf.stat.total_value": {"en": "Total value", "de": "Gesamtwert"},
    "report_pdf.table.rank": {"en": "#", "de": "#"},
    "report_pdf.table.user": {"en": "User", "de": "Person"},
    "report_pdf.table.points": {"en": "Points", "de": "Punkte"},
    "report_pdf.table.share": {"en": "Share", "de": "Anteil"},
    "report_pdf.table.approx_currency": {"en": "≈ {currency}", "de": "≈ {currency}"},
    "report_pdf.footer": {
        "en": "Household System · generated by {by}",
        "de": "Household System · erstellt von {by}",
    },
    "report_pdf.page_number": {"en": "Page {n}", "de": "Seite {n}"},
}


def t(lang: Lang, key: str, **params: object) -> str:
    """Looks up `key` in `lang`, falling back to English if the key
    exists but that language doesn't (shouldn't happen — both are
    always filled in above — but matches the frontend's own fallback
    chain rather than raising), then substitutes `{param}` placeholders.
    Raises KeyError for a genuinely unknown key — a typo here is a bug
    worth surfacing immediately, not silently swallowing."""
    entry = _STRINGS[key]
    template = entry.get(lang) or entry["en"]
    return template.format(**params)
