"""Canonical fingering analysis pipeline.

Phase E2B establishes a deterministic pass-based architecture. Only
ValidationPass performs real work; all other passes are placeholders for later
phases and must return AnalysisResults unchanged.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Iterable

from .models import (
    AnalysisResults,
    AlternateFingering,
    DifficultyScore,
    FingerAssignment,
    FingeringAnalysis,
    NoteEvent,
    PerformanceAnalysis,
    PositionShift,
    PracticeAnalysis,
    ProjectState,
    QualityReport,
    StretchIssue,
    TabPosition,
    Timeline,
    TimelineEvent,
    stable_id,
)
from .melody_transcriber import MelodyTranscriber


class AnalysisPass:
    """Base interface for canonical analysis passes."""

    name = "analysis"

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        return analysis_results


class ValidationPass(AnalysisPass):
    """Validate that canonical project data can enter the analysis pipeline."""

    name = "validation"

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        self.validate_project_state(project_state)
        return analysis_results

    def validate_project_state(self, state: ProjectState) -> None:
        if not isinstance(state, ProjectState):
            raise TypeError("FingeringAnalyzer requires a ProjectState.")
        if not isinstance(state.timeline, Timeline):
            raise ValueError("ProjectState.timeline must be a Timeline.")

        self._validate_note_events(state.generated_events)
        self._validate_tab_positions(state.tab_positions, state.generated_events)
        self._validate_timeline(state.timeline, state.generated_events, state.tab_positions)

    @classmethod
    def _validate_note_events(cls, events: Iterable[NoteEvent]) -> None:
        event_tuple = tuple(events)
        cls._require_unique_ids(
            (event.event_id for event in event_tuple),
            entity_name="NoteEvent",
        )
        for event in event_tuple:
            if not isinstance(event, NoteEvent):
                raise ValueError("ProjectState.generated_events must contain NoteEvent objects.")
            if not event.event_id:
                raise ValueError("NoteEvent.event_id cannot be empty.")
            if not event.note:
                raise ValueError(f"NoteEvent {event.event_id} must include a note.")
            if not math.isfinite(event.start_s) or not math.isfinite(event.end_s):
                raise ValueError(f"NoteEvent {event.event_id} has invalid timing.")
            if event.start_s < 0 or event.end_s < event.start_s:
                raise ValueError(f"NoteEvent {event.event_id} has invalid timing.")

    @classmethod
    def _validate_tab_positions(
        cls,
        tabs: Iterable[TabPosition],
        events: Iterable[NoteEvent],
    ) -> None:
        tab_tuple = tuple(tabs)
        event_ids = {event.event_id for event in events}
        cls._require_unique_ids(
            (tab.position_id for tab in tab_tuple),
            entity_name="TabPosition",
        )
        for tab in tab_tuple:
            if not isinstance(tab, TabPosition):
                raise ValueError("ProjectState.tab_positions must contain TabPosition objects.")
            if not tab.position_id:
                raise ValueError("TabPosition.position_id cannot be empty.")
            if not tab.event_id:
                raise ValueError(f"TabPosition {tab.position_id} must reference a NoteEvent.")
            if tab.event_id not in event_ids:
                raise ValueError(
                    f"TabPosition {tab.position_id} references missing NoteEvent {tab.event_id}."
                )
            if tab.string_id < 1 or tab.string_id > 6:
                raise ValueError(f"TabPosition {tab.position_id} has invalid string_id.")
            if tab.fret < 0:
                raise ValueError(f"TabPosition {tab.position_id} has invalid fret.")

    @classmethod
    def _validate_timeline(
        cls,
        timeline: Timeline,
        events: Iterable[NoteEvent],
        tabs: Iterable[TabPosition],
    ) -> None:
        timeline_events = tuple(timeline.events)
        note_event_ids = {event.event_id for event in events}
        tab_by_id = {tab.position_id: tab for tab in tabs}

        if note_event_ids and not timeline_events:
            raise ValueError("ProjectState.timeline must include events for generated notes.")
        if timeline.duration_s < 0 or timeline.duration_beats < 0:
            raise ValueError("Timeline duration cannot be negative.")

        cls._require_unique_ids(
            (event.timeline_event_id for event in timeline_events),
            entity_name="TimelineEvent",
        )

        timeline_note_event_ids: set[str] = set()
        for event in timeline_events:
            if not isinstance(event, TimelineEvent):
                raise ValueError("Timeline.events must contain TimelineEvent objects.")
            if not event.timeline_event_id:
                raise ValueError("TimelineEvent.timeline_event_id cannot be empty.")
            if event.note_event_id not in note_event_ids:
                raise ValueError(
                    f"TimelineEvent {event.timeline_event_id} references missing "
                    f"NoteEvent {event.note_event_id}."
                )
            if not math.isfinite(event.start_s) or not math.isfinite(event.duration_s):
                raise ValueError(f"TimelineEvent {event.timeline_event_id} has invalid timing.")
            if event.start_s < 0 or event.duration_s < 0:
                raise ValueError(f"TimelineEvent {event.timeline_event_id} has invalid timing.")
            timeline_note_event_ids.add(event.note_event_id)

            if event.tab_position_id is None:
                continue
            tab = tab_by_id.get(event.tab_position_id)
            if tab is None:
                raise ValueError(
                    f"TimelineEvent {event.timeline_event_id} references missing "
                    f"TabPosition {event.tab_position_id}."
                )
            if tab.event_id != event.note_event_id:
                raise ValueError(
                    f"TimelineEvent {event.timeline_event_id} links mismatched note and tab IDs."
                )

        missing_timeline_events = note_event_ids.difference(timeline_note_event_ids)
        if missing_timeline_events:
            missing = sorted(missing_timeline_events)[0]
            raise ValueError(f"NoteEvent {missing} is missing from the Timeline.")

    @staticmethod
    def _require_unique_ids(ids: Iterable[str], *, entity_name: str) -> None:
        seen: set[str] = set()
        for raw_id in ids:
            if not raw_id:
                continue
            if raw_id in seen:
                raise ValueError(f"Duplicate {entity_name} ID: {raw_id}.")
            seen.add(raw_id)


class FingerAssignmentPass(AnalysisPass):
    """Assign deterministic fretting-hand fingers to timeline events."""

    name = "finger_assignment"

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        tab_by_id = {tab.position_id: tab for tab in project_state.tab_positions}
        timeline_events = tuple(project_state.timeline.events)
        assignments: list[FingerAssignment] = []
        current_position_fret: int | None = None
        previous_assignment: FingerAssignment | None = None
        previous_tab: TabPosition | None = None

        for index, event in enumerate(timeline_events, start=1):
            tab = tab_by_id.get(event.tab_position_id) if event.tab_position_id else None
            assignment = self._assign_event(
                index=index,
                event=event,
                tab=tab,
                timeline_events=timeline_events,
                tab_by_id=tab_by_id,
                current_position_fret=current_position_fret,
                previous_assignment=previous_assignment,
                previous_tab=previous_tab,
            )
            assignments.append(assignment)
            if assignment.position_fret is not None and assignment.finger is not None:
                current_position_fret = assignment.position_fret
            previous_assignment = assignment
            previous_tab = tab

        fingering = replace(
            analysis_results.fingering,
            assignments=tuple(assignments),
        )
        return replace(analysis_results, fingering=fingering)

    def _assign_event(
        self,
        *,
        index: int,
        event: TimelineEvent,
        tab: TabPosition | None,
        timeline_events: tuple[TimelineEvent, ...],
        tab_by_id: dict[str, TabPosition],
        current_position_fret: int | None,
        previous_assignment: FingerAssignment | None,
        previous_tab: TabPosition | None,
    ) -> FingerAssignment:
        assignment_id = stable_id("finger_assignment", index)

        if tab is None:
            return FingerAssignment(
                assignment_id=assignment_id,
                timeline_event_id=event.timeline_event_id,
                note_event_id=event.note_event_id,
                tab_position_id=event.tab_position_id,
                finger=None,
                position_fret=current_position_fret,
                confidence=0.0,
                reason="no_tab_position",
            )

        if tab.fret == 0:
            return FingerAssignment(
                assignment_id=assignment_id,
                timeline_event_id=event.timeline_event_id,
                note_event_id=event.note_event_id,
                tab_position_id=tab.position_id,
                finger=None,
                position_fret=current_position_fret,
                confidence=1.0,
                reason="open_string",
            )

        if self._is_repeated_note(tab, previous_tab) and previous_assignment is not None:
            if self._finger_valid_for_fret(
                previous_assignment.finger,
                previous_assignment.position_fret,
                tab.fret,
            ):
                return FingerAssignment(
                    assignment_id=assignment_id,
                    timeline_event_id=event.timeline_event_id,
                    note_event_id=event.note_event_id,
                    tab_position_id=tab.position_id,
                    finger=previous_assignment.finger,
                    position_fret=previous_assignment.position_fret,
                    confidence=1.0,
                    reason="repeated_note",
                )

        position_fret = current_position_fret
        if not self._position_covers(position_fret, tab.fret):
            position_fret = self._choose_position(
                event_index=index - 1,
                fret=tab.fret,
                timeline_events=timeline_events,
                tab_by_id=tab_by_id,
            )

        finger = self._finger_for_position(position_fret, tab.fret)
        if finger is None:
            position_fret = max(1, tab.fret)
            finger = 1

        return FingerAssignment(
            assignment_id=assignment_id,
            timeline_event_id=event.timeline_event_id,
            note_event_id=event.note_event_id,
            tab_position_id=tab.position_id,
            finger=finger,
            position_fret=position_fret,
            confidence=1.0,
            reason="one_finger_per_fret",
        )

    @staticmethod
    def _is_repeated_note(tab: TabPosition, previous_tab: TabPosition | None) -> bool:
        return (
            previous_tab is not None
            and tab.string_id == previous_tab.string_id
            and tab.fret == previous_tab.fret
        )

    @staticmethod
    def _finger_valid_for_fret(
        finger: int | None,
        position_fret: int | None,
        fret: int,
    ) -> bool:
        if finger is None or position_fret is None:
            return False
        return 1 <= finger <= 4 and position_fret + finger - 1 == fret

    @staticmethod
    def _position_covers(position_fret: int | None, fret: int) -> bool:
        return position_fret is not None and position_fret <= fret <= position_fret + 3

    def _choose_position(
        self,
        *,
        event_index: int,
        fret: int,
        timeline_events: tuple[TimelineEvent, ...],
        tab_by_id: dict[str, TabPosition],
    ) -> int:
        frets = [fret]
        for event in timeline_events[event_index + 1 : event_index + 4]:
            if event.tab_position_id is None:
                continue
            tab = tab_by_id.get(event.tab_position_id)
            if tab is not None and tab.fret > 0:
                frets.append(tab.fret)

        low = min(frets)
        high = max(frets)
        if high - low <= 3:
            return max(1, low)
        return max(1, fret)

    @staticmethod
    def _finger_for_position(position_fret: int, fret: int) -> int | None:
        finger = fret - position_fret + 1
        if 1 <= finger <= 4:
            return finger
        return None


class StretchAnalysisPass(AnalysisPass):
    """Detect obvious stretches between consecutive fretted assignments."""

    name = "stretch_analysis"

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        tab_by_id = {tab.position_id: tab for tab in project_state.tab_positions}
        issues: list[StretchIssue] = []
        previous_assignment: FingerAssignment | None = None
        previous_tab: TabPosition | None = None

        for assignment in analysis_results.fingering.assignments:
            tab = (
                tab_by_id.get(assignment.tab_position_id)
                if assignment.tab_position_id is not None
                else None
            )
            if not self._is_fretted_assignment(assignment, tab):
                previous_assignment = None
                previous_tab = None
                continue

            if previous_assignment is not None and previous_tab is not None and tab is not None:
                issue = self._stretch_issue(
                    issue_index=len(issues) + 1,
                    previous_assignment=previous_assignment,
                    current_assignment=assignment,
                    previous_tab=previous_tab,
                    current_tab=tab,
                )
                if issue is not None:
                    issues.append(issue)

            previous_assignment = assignment
            previous_tab = tab

        fingering = replace(
            analysis_results.fingering,
            stretch_issues=tuple(issues),
        )
        return replace(analysis_results, fingering=fingering)

    @staticmethod
    def _is_fretted_assignment(
        assignment: FingerAssignment,
        tab: TabPosition | None,
    ) -> bool:
        return tab is not None and tab.fret > 0 and assignment.finger is not None

    def _stretch_issue(
        self,
        *,
        issue_index: int,
        previous_assignment: FingerAssignment,
        current_assignment: FingerAssignment,
        previous_tab: TabPosition,
        current_tab: TabPosition,
    ) -> StretchIssue | None:
        low_fret = min(previous_tab.fret, current_tab.fret)
        high_fret = max(previous_tab.fret, current_tab.fret)
        fret_span = high_fret - low_fret + 1
        if fret_span <= 4:
            return None

        severity = self._severity_for_span(fret_span)
        reason = "span_exceeds_one_finger_per_fret"
        return StretchIssue(
            issue_id=stable_id("stretch_issue", issue_index),
            timeline_event_ids=(
                previous_assignment.timeline_event_id,
                current_assignment.timeline_event_id,
            ),
            assignment_ids=(
                previous_assignment.assignment_id,
                current_assignment.assignment_id,
            ),
            note_event_ids=(
                previous_assignment.note_event_id,
                current_assignment.note_event_id,
            ),
            tab_position_ids=(
                previous_tab.position_id,
                current_tab.position_id,
            ),
            fret_span=fret_span,
            position_fret=previous_assignment.position_fret,
            severity=severity,
            reason=reason,
            confidence=0.9,
            message=f"Consecutive fretted notes span {fret_span} frets.",
            suggested_position_fret=None,
        )

    @staticmethod
    def _severity_for_span(fret_span: int) -> str:
        if fret_span >= 7:
            return "high"
        if fret_span >= 6:
            return "warn"
        return "info"


class PositionShiftPass(AnalysisPass):
    """Detect obvious hand-position changes in existing assignments."""

    name = "position_shift"

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        shifts: list[PositionShift] = []
        previous_assignment: FingerAssignment | None = None

        for assignment in analysis_results.fingering.assignments:
            if not self._is_fretted_assignment(assignment):
                continue

            if (
                previous_assignment is not None
                and previous_assignment.position_fret is not None
                and assignment.position_fret is not None
                and previous_assignment.position_fret != assignment.position_fret
            ):
                shifts.append(
                    self._position_shift(
                        shift_index=len(shifts) + 1,
                        previous_assignment=previous_assignment,
                        current_assignment=assignment,
                    )
                )

            previous_assignment = assignment

        fingering = replace(
            analysis_results.fingering,
            position_shifts=tuple(shifts),
        )
        return replace(analysis_results, fingering=fingering)

    @staticmethod
    def _is_fretted_assignment(assignment: FingerAssignment) -> bool:
        return assignment.finger is not None and assignment.position_fret is not None

    @staticmethod
    def _position_shift(
        *,
        shift_index: int,
        previous_assignment: FingerAssignment,
        current_assignment: FingerAssignment,
    ) -> PositionShift:
        from_position = previous_assignment.position_fret
        to_position = current_assignment.position_fret
        distance = abs((to_position or 0) - (from_position or 0))
        return PositionShift(
            shift_id=stable_id("position_shift", shift_index),
            from_timeline_event_id=previous_assignment.timeline_event_id,
            to_timeline_event_id=current_assignment.timeline_event_id,
            from_note_event_id=previous_assignment.note_event_id,
            to_note_event_id=current_assignment.note_event_id,
            from_tab_position_id=previous_assignment.tab_position_id,
            to_tab_position_id=current_assignment.tab_position_id,
            from_position_fret=from_position,
            to_position_fret=to_position,
            distance=distance,
            confidence=1.0,
            reason="position_fret_changed",
        )


class DifficultyPass(AnalysisPass):
    """Compute deterministic difficulty from existing fingering analysis."""

    name = "difficulty"

    _STRETCH_WEIGHTS = {
        "info": 6.0,
        "warn": 12.0,
        "high": 20.0,
    }

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        assignments = analysis_results.fingering.assignments
        stretch_issues = analysis_results.fingering.stretch_issues
        position_shifts = analysis_results.fingering.position_shifts

        stretch_score = self._stretch_score(stretch_issues)
        position_shift_score = self._position_shift_score(position_shifts)
        movement_score = self._movement_score(position_shifts)
        finger_complexity_score = self._finger_complexity_score(assignments)
        open_string_bonus = self._open_string_bonus(assignments)
        overall_score = self._clamp_score(
            stretch_score
            + position_shift_score
            + movement_score
            + finger_complexity_score
            - open_string_bonus
        )
        difficulty_level = self._difficulty_level(overall_score)
        reason_summary = self._reason_summary(
            stretch_score=stretch_score,
            position_shift_score=position_shift_score,
            movement_score=movement_score,
            finger_complexity_score=finger_complexity_score,
            open_string_bonus=open_string_bonus,
        )
        difficulty = DifficultyScore(
            score_id=stable_id("difficulty", 1),
            overall=overall_score,
            label=difficulty_level,
            stretch=stretch_score,
            movement=movement_score,
            position_shifts=position_shift_score,
            fingering=finger_complexity_score,
            confidence=1.0,
            overall_score=overall_score,
            difficulty_level=difficulty_level,
            stretch_score=stretch_score,
            movement_score=movement_score,
            position_shift_score=position_shift_score,
            finger_complexity_score=finger_complexity_score,
            open_string_bonus=open_string_bonus,
            reason_summary=reason_summary,
        )
        performance = replace(analysis_results.performance, difficulty=difficulty)
        return replace(analysis_results, performance=performance)

    def _stretch_score(self, stretch_issues: tuple[StretchIssue, ...]) -> float:
        total = 0.0
        for issue in stretch_issues:
            total += self._STRETCH_WEIGHTS.get(issue.severity, 6.0)
            total += max(0, issue.fret_span - 4) * 2.0
        return self._clamp_component(total, 35.0)

    @staticmethod
    def _position_shift_score(position_shifts: tuple[PositionShift, ...]) -> float:
        total = 0.0
        for shift in position_shifts:
            total += 5.0
            total += max(0, shift.distance - 3) * 2.0
        return DifficultyPass._clamp_component(total, 25.0)

    @staticmethod
    def _movement_score(position_shifts: tuple[PositionShift, ...]) -> float:
        total_distance = sum(shift.distance for shift in position_shifts)
        return DifficultyPass._clamp_component(total_distance * 1.5, 20.0)

    @staticmethod
    def _finger_complexity_score(assignments: tuple[FingerAssignment, ...]) -> float:
        fretted = [assignment for assignment in assignments if assignment.finger is not None]
        if not fretted:
            return 0.0
        weak_finger_uses = sum(1 for assignment in fretted if assignment.finger in (3, 4))
        weak_finger_repeats = 0
        previous_finger: int | None = None
        for assignment in fretted:
            if assignment.finger in (3, 4) and assignment.finger == previous_finger:
                weak_finger_repeats += 1
            previous_finger = assignment.finger
        total = weak_finger_uses * 1.5 + weak_finger_repeats * 1.0
        return DifficultyPass._clamp_component(total, 15.0)

    @staticmethod
    def _open_string_bonus(assignments: tuple[FingerAssignment, ...]) -> float:
        open_strings = sum(1 for assignment in assignments if assignment.finger is None)
        return DifficultyPass._clamp_component(open_strings * 1.5, 8.0)

    @staticmethod
    def _difficulty_level(overall_score: float) -> str:
        if overall_score <= 20.0:
            return "Easy"
        if overall_score <= 45.0:
            return "Moderate"
        if overall_score <= 70.0:
            return "Hard"
        return "Expert"

    @staticmethod
    def _reason_summary(
        *,
        stretch_score: float,
        position_shift_score: float,
        movement_score: float,
        finger_complexity_score: float,
        open_string_bonus: float,
    ) -> str:
        return (
            f"stretch={stretch_score:.1f}; "
            f"position_shifts={position_shift_score:.1f}; "
            f"movement={movement_score:.1f}; "
            f"finger_complexity={finger_complexity_score:.1f}; "
            f"open_string_bonus={open_string_bonus:.1f}"
        )

    @staticmethod
    def _clamp_component(value: float, maximum: float) -> float:
        return round(max(0.0, min(maximum, value)), 2)

    @staticmethod
    def _clamp_score(value: float) -> float:
        return round(max(0.0, min(100.0, value)), 2)


class QualityPass(AnalysisPass):
    """Evaluate ergonomic quality without changing prior analysis."""

    name = "quality"

    _STRETCH_PENALTIES = {
        "info": 8.0,
        "warn": 16.0,
        "high": 25.0,
    }

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        assignments = analysis_results.fingering.assignments
        stretch_issues = analysis_results.fingering.stretch_issues
        position_shifts = analysis_results.fingering.position_shifts

        stretch_penalty = self._stretch_penalty(stretch_issues)
        shift_penalty = self._shift_penalty(position_shifts)
        movement_penalty = self._movement_penalty(position_shifts)
        finger_change_penalty = self._finger_change_penalty(assignments)
        open_string_penalty = self._open_string_penalty(assignments)
        compact_bonus = self._compact_bonus(assignments, stretch_issues, position_shifts)

        score = self._clamp_score(
            100.0
            - stretch_penalty
            - shift_penalty
            - movement_penalty
            - finger_change_penalty
            - open_string_penalty
            + compact_bonus
        )
        quality_level = self._quality_level(score)
        issues = self._quality_issues(
            stretch_penalty=stretch_penalty,
            shift_penalty=shift_penalty,
            movement_penalty=movement_penalty,
            finger_change_penalty=finger_change_penalty,
            open_string_penalty=open_string_penalty,
        )
        recommendations = self._recommendations(issues)
        summary = self._summary(
            score=score,
            quality_level=quality_level,
            stretch_penalty=stretch_penalty,
            shift_penalty=shift_penalty,
            movement_penalty=movement_penalty,
            finger_change_penalty=finger_change_penalty,
            open_string_penalty=open_string_penalty,
            compact_bonus=compact_bonus,
        )
        quality = QualityReport(
            score=score,
            warnings=recommendations,
            metrics={
                "stretch_penalty": stretch_penalty,
                "shift_penalty": shift_penalty,
                "movement_penalty": movement_penalty,
                "finger_change_penalty": finger_change_penalty,
                "open_string_penalty": open_string_penalty,
                "compact_bonus": compact_bonus,
                "difficulty_score": analysis_results.performance.difficulty.overall_score,
            },
            overall_quality_score=score,
            quality_level=quality_level,
            quality_issues=issues,
            recommendations=recommendations,
            confidence=1.0,
            summary=summary,
        )
        return replace(analysis_results, quality=quality)

    def _stretch_penalty(self, stretch_issues: tuple[StretchIssue, ...]) -> float:
        total = 0.0
        for issue in stretch_issues:
            total += self._STRETCH_PENALTIES.get(issue.severity, 8.0)
            total += max(0, issue.fret_span - 4) * 1.5
        return self._clamp_component(total, 30.0)

    @staticmethod
    def _shift_penalty(position_shifts: tuple[PositionShift, ...]) -> float:
        total = 0.0
        for shift in position_shifts:
            total += 8.0
            total += max(0, shift.distance - 3) * 2.0
        return QualityPass._clamp_component(total, 25.0)

    @staticmethod
    def _movement_penalty(position_shifts: tuple[PositionShift, ...]) -> float:
        total_distance = sum(shift.distance for shift in position_shifts)
        return QualityPass._clamp_component(total_distance * 1.25, 20.0)

    @staticmethod
    def _finger_change_penalty(assignments: tuple[FingerAssignment, ...]) -> float:
        fretted_fingers = [
            assignment.finger for assignment in assignments if assignment.finger is not None
        ]
        if len(fretted_fingers) < 2:
            return 0.0
        changes = sum(
            1
            for previous, current in zip(fretted_fingers, fretted_fingers[1:])
            if previous != current
        )
        comfortable_changes = max(0, len(fretted_fingers) - 1)
        excess_changes = max(0, changes - comfortable_changes)
        return QualityPass._clamp_component(excess_changes * 2.0, 15.0)

    @staticmethod
    def _open_string_penalty(assignments: tuple[FingerAssignment, ...]) -> float:
        if not assignments:
            return 0.0
        open_string_count = sum(1 for assignment in assignments if assignment.finger is None)
        fretted_count = len(assignments) - open_string_count
        if fretted_count == 0:
            return 0.0
        open_ratio = open_string_count / len(assignments)
        if open_ratio <= 0.6:
            return 0.0
        return QualityPass._clamp_component((open_ratio - 0.6) * 20.0, 10.0)

    @staticmethod
    def _compact_bonus(
        assignments: tuple[FingerAssignment, ...],
        stretch_issues: tuple[StretchIssue, ...],
        position_shifts: tuple[PositionShift, ...],
    ) -> float:
        fretted_count = sum(1 for assignment in assignments if assignment.finger is not None)
        if fretted_count == 0 or stretch_issues or position_shifts:
            return 0.0
        return 5.0

    @staticmethod
    def _quality_level(score: float) -> str:
        if score >= 90.0:
            return "Excellent"
        if score >= 75.0:
            return "Good"
        if score >= 55.0:
            return "Fair"
        return "Poor"

    @staticmethod
    def _quality_issues(
        *,
        stretch_penalty: float,
        shift_penalty: float,
        movement_penalty: float,
        finger_change_penalty: float,
        open_string_penalty: float,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if stretch_penalty > 0:
            issues.append("unnecessary_stretches")
        if shift_penalty > 0:
            issues.append("unnecessary_position_shifts")
        if movement_penalty >= 10.0:
            issues.append("inefficient_movement")
        if finger_change_penalty > 0:
            issues.append("excessive_finger_changes")
        if open_string_penalty > 0:
            issues.append("poor_open_string_usage")
        return tuple(issues)

    @staticmethod
    def _recommendations(issues: tuple[str, ...]) -> tuple[str, ...]:
        recommendation_by_issue = {
            "unnecessary_stretches": "Use a more compact fret span where possible.",
            "unnecessary_position_shifts": "Keep the hand in one position when adjacent notes allow it.",
            "inefficient_movement": "Reduce large position jumps between consecutive notes.",
            "excessive_finger_changes": "Reuse stable fingers for repeated or nearby frets.",
            "poor_open_string_usage": "Balance open strings with fretted notes for a stable hand position.",
        }
        return tuple(recommendation_by_issue[issue] for issue in issues)

    @staticmethod
    def _summary(
        *,
        score: float,
        quality_level: str,
        stretch_penalty: float,
        shift_penalty: float,
        movement_penalty: float,
        finger_change_penalty: float,
        open_string_penalty: float,
        compact_bonus: float,
    ) -> str:
        return (
            f"{quality_level} quality ({score:.1f}/100): "
            f"stretch_penalty={stretch_penalty:.1f}; "
            f"shift_penalty={shift_penalty:.1f}; "
            f"movement_penalty={movement_penalty:.1f}; "
            f"finger_change_penalty={finger_change_penalty:.1f}; "
            f"open_string_penalty={open_string_penalty:.1f}; "
            f"compact_bonus={compact_bonus:.1f}"
        )

    @staticmethod
    def _clamp_component(value: float, maximum: float) -> float:
        return round(max(0.0, min(maximum, value)), 2)

    @staticmethod
    def _clamp_score(value: float) -> float:
        return round(max(0.0, min(100.0, value)), 2)


class AlternateFingeringPass(AnalysisPass):
    """Generate and rank complete alternate tab-position phrases."""

    name = "alternate_fingering"

    def __init__(self, *, max_candidates: int = 3, beam_width: int = 24) -> None:
        self.max_candidates = max(0, max_candidates)
        self.beam_width = max(1, beam_width)

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        if self.max_candidates == 0 or not project_state.timeline.events:
            return analysis_results

        candidate_paths = self._candidate_paths(project_state)
        if not candidate_paths:
            return analysis_results

        original_signature = self._original_signature(project_state)
        evaluated = []
        candidate_index = 1
        for path in candidate_paths:
            path_signature = self._path_signature(path)
            if path_signature == original_signature:
                continue
            candidate_state = self._candidate_state(
                project_state=project_state,
                path=path,
                candidate_index=candidate_index,
            )
            candidate_results = self._evaluate_candidate(candidate_state)
            evaluated.append((path_signature, candidate_state, candidate_results))
            candidate_index += 1

        ranked = sorted(evaluated, key=self._ranking_key)[: self.max_candidates]
        alternates = tuple(
            self._alternate_fingering(
                rank=rank,
                candidate_state=candidate_state,
                candidate_results=candidate_results,
            )
            for rank, (_, candidate_state, candidate_results) in enumerate(ranked, start=1)
        )
        if not alternates:
            return analysis_results

        fingering = replace(
            analysis_results.fingering,
            alternate_fingerings=alternates,
        )
        return replace(analysis_results, fingering=fingering)

    def _candidate_paths(self, project_state: ProjectState) -> tuple[tuple[TabPosition, ...], ...]:
        note_by_id = {event.event_id: event for event in project_state.generated_events}
        max_fret = max((tab.fret for tab in project_state.tab_positions), default=15)
        transcriber = MelodyTranscriber(min_fret=0, max_fret=max(15, max_fret))
        paths: list[tuple[TabPosition, ...]] = [()]

        for timeline_event in project_state.timeline.events:
            note_event = note_by_id.get(timeline_event.note_event_id)
            if note_event is None:
                return ()
            options = tuple(
                transcriber._candidate_positions(note_event.midi, event_id=note_event.event_id)
            )
            if not options:
                return ()

            expanded = [path + (option,) for path in paths for option in options]
            paths = sorted(expanded, key=self._path_sort_key)[: self.beam_width]

        return tuple(paths)

    @staticmethod
    def _path_sort_key(path: tuple[TabPosition, ...]) -> tuple[tuple[int, int], ...]:
        return tuple((position.fret, position.string_id) for position in path)

    @staticmethod
    def _path_signature(path: tuple[TabPosition, ...]) -> tuple[tuple[int, int], ...]:
        return tuple((position.string_id, position.fret) for position in path)

    @staticmethod
    def _original_signature(project_state: ProjectState) -> tuple[tuple[int, int], ...]:
        tab_by_id = {tab.position_id: tab for tab in project_state.tab_positions}
        signature: list[tuple[int, int]] = []
        for event in project_state.timeline.events:
            tab = tab_by_id.get(event.tab_position_id) if event.tab_position_id else None
            if tab is None:
                return ()
            signature.append((tab.string_id, tab.fret))
        return tuple(signature)

    @staticmethod
    def _candidate_state(
        *,
        project_state: ProjectState,
        path: tuple[TabPosition, ...],
        candidate_index: int,
    ) -> ProjectState:
        replacement_tabs = tuple(
            replace(
                position,
                position_id=stable_id(f"alternate_{candidate_index}_tab", index),
            )
            for index, position in enumerate(path, start=1)
        )
        replacement_events = tuple(
            replace(
                timeline_event,
                tab_position_id=tab.position_id,
                string=tab.string_id,
                fret=tab.fret,
            )
            for timeline_event, tab in zip(project_state.timeline.events, replacement_tabs)
        )
        return replace(
            project_state,
            tab_positions=replacement_tabs,
            timeline=replace(project_state.timeline, events=replacement_events),
            analysis_results=AnalysisResults(),
        )

    @staticmethod
    def _evaluate_candidate(candidate_state: ProjectState) -> AnalysisResults:
        analyzer = FingeringAnalyzer(
            passes=(
                ValidationPass(),
                FingerAssignmentPass(),
                StretchAnalysisPass(),
                PositionShiftPass(),
                DifficultyPass(),
                QualityPass(),
            )
        )
        return analyzer.analyze_results(candidate_state)

    @staticmethod
    def _ranking_key(
        item: tuple[tuple[tuple[int, int], ...], ProjectState, AnalysisResults],
    ) -> tuple[float, float, int, int, int, float, tuple[tuple[int, int], ...]]:
        path_signature, _, candidate_results = item
        quality_score = candidate_results.quality.overall_quality_score or 0.0
        difficulty = candidate_results.performance.difficulty
        movement = sum(shift.distance for shift in candidate_results.fingering.position_shifts)
        return (
            -quality_score,
            difficulty.overall_score,
            len(candidate_results.fingering.stretch_issues),
            len(candidate_results.fingering.position_shifts),
            movement,
            -difficulty.open_string_bonus,
            path_signature,
        )

    @staticmethod
    def _alternate_fingering(
        *,
        rank: int,
        candidate_state: ProjectState,
        candidate_results: AnalysisResults,
    ) -> AlternateFingering:
        candidate_id = stable_id("alternate_candidate", rank)
        timeline_event_ids = tuple(
            event.timeline_event_id for event in candidate_state.timeline.events
        )
        note_event_ids = tuple(event.note_event_id for event in candidate_state.timeline.events)
        quality_score = candidate_results.quality.overall_quality_score or 0.0
        difficulty = candidate_results.performance.difficulty
        stretch_count = len(candidate_results.fingering.stretch_issues)
        shift_count = len(candidate_results.fingering.position_shifts)
        tradeoffs = AlternateFingeringPass._tradeoffs(candidate_results)
        summary = (
            f"Quality {quality_score:.1f}, difficulty {difficulty.overall_score:.1f}, "
            f"stretches {stretch_count}, shifts {shift_count}."
        )
        return AlternateFingering(
            alternate_id=stable_id("alternate_fingering", rank),
            candidate_id=candidate_id,
            timeline_event_ids=timeline_event_ids,
            note_event_ids=note_event_ids,
            tab_positions=candidate_state.tab_positions,
            replacement_tab_positions=candidate_state.tab_positions,
            finger_assignments=candidate_results.fingering.assignments,
            quality_score=quality_score,
            difficulty_score=difficulty,
            tradeoffs=tradeoffs,
            summary=summary,
            confidence=candidate_results.quality.confidence,
        )

    @staticmethod
    def _tradeoffs(candidate_results: AnalysisResults) -> tuple[str, ...]:
        tradeoffs: list[str] = []
        stretch_count = len(candidate_results.fingering.stretch_issues)
        shift_count = len(candidate_results.fingering.position_shifts)
        if stretch_count:
            tradeoffs.append(f"{stretch_count} stretch issue(s).")
        if shift_count:
            tradeoffs.append(f"{shift_count} position shift(s).")
        tradeoffs.extend(candidate_results.quality.recommendations[:2])
        if not tradeoffs:
            tradeoffs.append("Compact fingering with stable hand position.")
        return tuple(tradeoffs)


class PracticePreparationPass(AnalysisPass):
    """Placeholder for future practice preparation."""

    name = "practice_preparation"


class FingeringAnalyzer:
    """Orchestrate deterministic Phase E analysis passes."""

    def __init__(self, passes: Iterable[AnalysisPass] | None = None) -> None:
        self.passes = tuple(passes) if passes is not None else self.default_passes()

    @staticmethod
    def default_passes() -> tuple[AnalysisPass, ...]:
        return (
            ValidationPass(),
            FingerAssignmentPass(),
            StretchAnalysisPass(),
            PositionShiftPass(),
            DifficultyPass(),
            QualityPass(),
            AlternateFingeringPass(),
            PracticePreparationPass(),
        )

    def analyze(self, state: ProjectState) -> ProjectState:
        """Run the pass pipeline and return a ProjectState copy with results."""
        self._require_project_state(state)
        analysis_results = self._empty_results(self._timeline_id(state))
        for analysis_pass in self.passes:
            analysis_results = analysis_pass.run(state, analysis_results)
            if not isinstance(analysis_results, AnalysisResults):
                raise TypeError(
                    f"{analysis_pass.__class__.__name__}.run() must return AnalysisResults."
                )
        return replace(state, analysis_results=analysis_results)

    def analyze_results(self, state: ProjectState) -> AnalysisResults:
        """Run the pass pipeline and return only AnalysisResults."""
        return self.analyze(state).analysis_results

    def analyze_project_state(self, state: ProjectState) -> ProjectState:
        """Return a ProjectState copy with canonical analysis results attached."""
        return self.analyze(state)

    def validate_project_state(self, state: ProjectState) -> None:
        """Validate that a project can enter the Phase E analysis pipeline."""
        ValidationPass().validate_project_state(state)

    @staticmethod
    def _require_project_state(state: ProjectState) -> None:
        if not isinstance(state, ProjectState):
            raise TypeError("FingeringAnalyzer requires a ProjectState.")

    @staticmethod
    def _timeline_id(state: ProjectState) -> str | None:
        timeline = state.timeline
        return timeline.timeline_id if isinstance(timeline, Timeline) else None

    @staticmethod
    def _empty_results(timeline_id: str | None) -> AnalysisResults:
        return AnalysisResults(
            analysis_id=stable_id("analysis_results", 1),
            fingering=FingeringAnalysis(
                analysis_id=stable_id("fingering_analysis", 1),
            ),
            performance=PerformanceAnalysis(
                analysis_id=stable_id("performance_analysis", 1),
                difficulty=DifficultyScore(score_id=stable_id("difficulty", 1)),
            ),
            quality=QualityReport(),
            practice=PracticeAnalysis(
                analysis_id=stable_id("practice_analysis", 1),
            ),
            generated_from_timeline_id=timeline_id,
        )
