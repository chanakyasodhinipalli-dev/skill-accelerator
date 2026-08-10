"""What to ask about next — grouped by how the fields relate, not by section.

Sections are how the *author* filed the fields. They are a real signal and this
module still uses one, but they are the wrong unit to converse in, for a reason
that shows up in every form: the person answering does not hold the author's
filing system in their head. They hold the change.

    Overview  → change owner
    Sign-off  → technical reviewer, business approver

Three fields, two sections, and exactly one question a human would ask: "who's
driving this, who reviewed it, and who's signing it off?" Asking by section
splits that in two and puts eight questions between the halves.

So a **topic** here is computed. Fields are scored against each other on
signals already present in the definition — an authored relationship, a shared
guard, co-membership in a consistency rule, shared vocabulary, the same kind of
answer, the same section — and the batch that gets asked about is the tightest
cluster around whatever should be asked next.

Two properties are kept from the section-ordered design, because both were
right:

* **Selection stays deterministic.** Only the wording is generated. Affinity is
  arithmetic over the definition, so the same session always produces the same
  next question and a form author can reason about it.
* **The author's order still leads.** Cohesion decides what a question *covers*;
  it does not decide where the conversation starts. A form that opens on
  "what are you changing" continues to, because nothing is more related to
  nothing than the first mandatory field is.

The one case where affinity overrides declared order is an *authored*
relationship — `related_fields`, an `ask_when` guard, a consistency rule naming
both. The author has said those two belong together, and honouring that
immediately is the whole point of saying it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from .models import FieldType, FormDefinition, FormField, FormSection

#: How many open-prose fields one question may cover. Two "describe X" asks in
#: the same breath come back as a single run-on answer, and splitting it between
#: the fields afterwards is guesswork that gets it wrong often enough to cost
#: more than asking twice.
MAX_PROSE_FIELDS = 1

#: Affinity at or above this is an *authored* relationship rather than an
#: inferred one: the form's author has stated that these two fields belong
#: together. That outranks the order sections happen to be declared in.
STRONG_AFFINITY = 4

#: Words that carry no grouping information. "Change owner" and "change title"
#: share "change" in a change request form and are not thereby related.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "be",
        "by",
        "change",
        "detail",
        "details",
        "for",
        "form",
        "from",
        "has",
        "have",
        "how",
        "id",
        "in",
        "info",
        "information",
        "is",
        "it",
        "level",
        "name",
        "of",
        "on",
        "or",
        "other",
        "plan",
        "request",
        "required",
        "the",
        "this",
        "to",
        "type",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    }
)

_WORD = re.compile(r"[a-z][a-z0-9]+")
_GUARD_REFERENCE = re.compile(r"answers\.([a-z][a-z0-9_]*)")


@dataclass(slots=True)
class Topic:
    """A group of fields to ask about in one breath.

    Deliberately shaped like a :class:`~sa_forms.models.FormSection` — it has an
    id, a title, a description and an opening prompt — because everything
    downstream wants to talk about "the current topic" and should not care
    whether that came from an author or from clustering.
    """

    id: str
    title: str
    fields: list[FormField]
    description: str = ""
    opening_prompt: str = ""
    #: Sections the fields were authored in, in declared order. More than one
    #: means this topic crosses a boundary the author drew.
    section_ids: list[str] = dataclass_field(default_factory=list)
    #: Total internal affinity. Diagnostic — high means the batch genuinely
    #: hangs together, 0 means these fields were batched for want of anything
    #: better and the question should stay narrow.
    cohesion: int = 0

    @property
    def spans_sections(self) -> bool:
        return len(self.section_ids) > 1


def _tokens(field: FormField) -> set[str]:
    """Meaningful words naming this field, from its label, id, and aliases."""
    text = " ".join([field.label, field.id.replace("_", " "), *field.aliases]).lower()
    return {w for w in _WORD.findall(text) if w not in _STOPWORDS and len(w) > 2}


@dataclass(slots=True)
class _Graph:
    """Pairwise affinity over a form's fields, computed once per turn."""

    weights: dict[tuple[str, str], int]

    def between(self, left: str, right: str) -> int:
        if left == right:
            return 0
        return self.weights.get((left, right) if left < right else (right, left), 0)

    def to_set(self, field_id: str, others: list[FormField]) -> int:
        return sum(self.between(field_id, other.id) for other in others)


def build_graph(form: FormDefinition) -> _Graph:
    """Score every pair of fields on how related they are.

    The weights are ordinal, not measured: what matters is that an authored
    relationship beats a shared word, and a shared word beats merely having been
    filed in the same section. Anything finer would be false precision.
    """
    fields = form.fields()
    section_of = {f.id: s.id for s in form.sections for f in s.fields}
    tokens = {f.id: _tokens(f) for f in fields}

    # Authored links, in both directions — `related_fields` is a statement about
    # a pair, and which side declared it is an accident of authoring.
    related: set[tuple[str, str]] = set()
    for field in fields:
        for other in field.related_fields:
            related.add((min(field.id, other), max(field.id, other)))

    # A guard is a dependency: `ask_when: ${answers.customer_impacting == true}`
    # means the comms owner is a follow-up to customer impact, and asking them
    # apart wastes the context the first answer just established.
    guarded: set[tuple[str, str]] = set()
    for field in fields:
        for referenced in _GUARD_REFERENCE.findall(field.ask_when or ""):
            if referenced != field.id and form.try_field(referenced) is not None:
                guarded.add((min(field.id, referenced), max(field.id, referenced)))

    # Fields a consistency rule compares are fields whose answers have to make
    # sense together. That is the same thing as belonging in one question.
    ruled: set[tuple[str, str]] = set()
    for rule in form.consistency_rules:
        members = [f for f in rule.fields if form.try_field(f) is not None]
        for position, first in enumerate(members):
            for second in members[position + 1 :]:
                ruled.add((min(first, second), max(first, second)))

    weights: dict[tuple[str, str], int] = {}
    for index, left in enumerate(fields):
        for right in fields[index + 1 :]:
            pair = (min(left.id, right.id), max(left.id, right.id))
            score = 0
            if pair in related:
                score += 4
            if pair in guarded:
                score += 4
            if pair in ruled:
                score += 3

            shared = tokens[left.id] & tokens[right.id]
            if shared:
                score += min(2 * len(shared), 4)

            # The same kind of answer is asked for in the same breath. Naming
            # three people is one question; a date and a person are two.
            if _same_answer_kind(left, right):
                score += 2

            if section_of.get(left.id) == section_of.get(right.id):
                score += 1

            if score:
                weights[pair] = score
    return _Graph(weights)


def _same_answer_kind(left: FormField, right: FormField) -> bool:
    """True when answering both calls for the same *sort* of thing."""
    people = {FieldType.PERSON, FieldType.EMAIL}
    times = {FieldType.DATE, FieldType.DATETIME, FieldType.DURATION}
    scales = {FieldType.ENUM, FieldType.INTEGER, FieldType.NUMBER, FieldType.CURRENCY}
    for family in (people, times, scales):
        if left.type in family and right.type in family:
            return True
    return left.requires_named_party and right.requires_named_party


def plan(
    form: FormDefinition,
    candidates: list[tuple[FormField, FormSection]],
    *,
    max_fields: int = 4,
    recently_settled: list[str] | None = None,
) -> Topic | None:
    """Choose the next topic from the fields still outstanding.

    ``candidates`` are the fields worth asking about, already filtered and in
    the author's declared order — this module decides grouping, not eligibility.

    Two steps, deliberately separate:

    1. **Pick the seed.** Mandatory work first, then the author's order — except
       where a field is strongly related to something just answered, which wins.
       That is what makes "you said customers are affected — who tells them?"
       follow immediately rather than eight questions later.
    2. **Grow around it.** Repeatedly add the outstanding field most related to
       what is already in the batch, wherever in the form it lives. Growth stops
       at the cap, at one prose field, or as soon as nothing is related to the
       batch at all — a fourth unrelated field does not make the question
       better, it makes it a form.
    """
    if not candidates:
        return None
    if not form.group_by_affinity:
        return _section_topic(candidates, max_fields=max_fields)

    graph = build_graph(form)
    order = {field.id: index for index, (field, _) in enumerate(candidates)}
    settled = recently_settled or []

    def continuity(field: FormField) -> int:
        """Strength of this field's link to what was just answered."""
        best = max((graph.between(field.id, other) for other in settled), default=0)
        return best if best >= STRONG_AFFINITY else 0

    seed, _ = min(
        candidates,
        key=lambda pair: (
            pair[0].importance.rank,
            -continuity(pair[0]),
            pair[1].order,
            order[pair[0].id],
        ),
    )

    chosen = [seed]
    prose = 1 if seed.type is FieldType.TEXT else 0
    remaining = [f for f, _ in candidates if f.id != seed.id]

    while len(chosen) < max_fields and remaining:
        scored = [(graph.to_set(f.id, chosen), f) for f in remaining]
        affinity, best = max(
            scored,
            key=lambda pair: (pair[0], -pair[1].importance.rank, -order[pair[1].id]),
        )
        if affinity <= 0:
            break  # nothing left that belongs in this question
        remaining = [f for f in remaining if f.id != best.id]
        if best.type is FieldType.TEXT:
            if prose >= MAX_PROSE_FIELDS:
                continue
            prose += 1
        chosen.append(best)

    return _build_topic(form, chosen, graph)


def _build_topic(form: FormDefinition, fields: list[FormField], graph: _Graph) -> Topic:
    """Name the chosen batch, borrowing from the sections it came from.

    A topic inside one section *is* that section, opening prompt and all — the
    author wrote a good line for it and clustering has no business discarding
    it. One that crosses a boundary gets a composed title, and no opening
    prompt: an authored opener describes its own section, and using it for a
    batch that reaches outside would promise a topic the question does not ask.
    """
    wanted = {f.id for f in fields}
    sections = [s for s in form.ordered_sections() if any(f.id in wanted for f in s.fields)]
    cohesion = sum(
        graph.between(left.id, right.id)
        for index, left in enumerate(fields)
        for right in fields[index + 1 :]
    )
    # Keep the author's declared order within the batch; it reads better than
    # affinity order, which is an artefact of the search.
    position = {f.id: i for i, f in enumerate(form.fields())}
    ordered = sorted(fields, key=lambda f: position.get(f.id, 999))

    if len(sections) == 1:
        section = sections[0]
        return Topic(
            id=section.id,
            title=section.title,
            fields=ordered,
            description=section.description,
            opening_prompt=section.opening_prompt,
            section_ids=[section.id],
            cohesion=cohesion,
        )

    return Topic(
        id="+".join(s.id for s in sections),
        title=" and ".join(s.title.lower() for s in sections).capitalize(),
        fields=ordered,
        description="; ".join(s.description for s in sections if s.description),
        section_ids=[s.id for s in sections],
        cohesion=cohesion,
    )


def _section_topic(candidates: list[tuple[FormField, FormSection]], *, max_fields: int) -> Topic:
    """The pre-affinity behaviour: one section at a time, in declared order.

    Kept because a form may legitimately want it — a regulated questionnaire
    whose section order is itself the requirement — and because it is the
    honest fallback when an author has said `group_by_affinity: false`.
    """
    section = min(candidates, key=lambda pair: pair[1].order)[1]
    in_section = [f for f, s in candidates if s.id == section.id]
    in_section.sort(key=lambda f: (f.importance.rank, [x.id for x in section.fields].index(f.id)))

    chosen: list[FormField] = []
    prose = 0
    for candidate in in_section:
        if candidate.type is FieldType.TEXT:
            if prose >= MAX_PROSE_FIELDS:
                continue
            prose += 1
        chosen.append(candidate)
        if len(chosen) >= max_fields:
            break

    return Topic(
        id=section.id,
        title=section.title,
        fields=chosen,
        description=section.description,
        opening_prompt=section.opening_prompt,
        section_ids=[section.id],
    )


def topic_of(form: FormDefinition, field_ids: list[str]) -> Topic:
    """Wrap known fields as a topic, for paths that already know what to ask.

    Confirmations and re-asks do not go through selection — they already have
    their fields — but everything downstream still wants a topic to talk about.
    """
    fields = [f for f in (form.try_field(fid) for fid in field_ids) if f is not None]
    if not fields:
        # An agreement form has no sections at all, so there is no first one to
        # fall back to. The empty topic is a real state, not a bug: it means
        # there is nothing to ask about, which is exactly true.
        sections = form.ordered_sections()
        if not sections:
            return Topic(id=form.name, title=form.title, fields=[], section_ids=[])
        first = sections[0]
        return Topic(id=first.id, title=first.title, fields=[], section_ids=[first.id])
    return _build_topic(form, fields, build_graph(form))


def related_to(form: FormDefinition, field_id: str, *, limit: int = 3) -> list[FormField]:
    """The fields most related to one field. Used when explaining it.

    "Blast radius" makes far more sense next to the rollback plan it exists to
    scope than it does on its own.
    """
    graph = build_graph(form)
    scored = [(graph.between(field_id, f.id), f) for f in form.fields() if f.id != field_id]
    ranked = sorted((s for s in scored if s[0] > 0), key=lambda pair: -pair[0])
    return [field for _, field in ranked[:limit]]


__all__ = [
    "MAX_PROSE_FIELDS",
    "STRONG_AFFINITY",
    "Topic",
    "build_graph",
    "plan",
    "related_to",
    "topic_of",
]
