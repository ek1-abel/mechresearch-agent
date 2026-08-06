"""LangGraph sidecar workflow for MechResearch-Agent.

The original project already follows a Planner-Executor / DeepResearch pattern.
This module keeps the existing FastAPI models, configuration, search, RAG,
note, reporting, and evaluator services, and adds a LangGraph orchestration
layer that can be used as an optional drop-in sidecar.
"""

from __future__ import annotations

import logging
import operator
from typing import Any, Iterator

from typing_extensions import Annotated, TypedDict

from agent import DeepResearchAgent
from config import Configuration
from models import EvaluationResult, SummaryState, SummaryStateOutput, TodoItem

try:  # Optional dependency: install backend/requirements-langgraph.txt.
    from langgraph.graph import END, StateGraph
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without langgraph.
    END = None
    StateGraph = None
    _LANGGRAPH_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _LANGGRAPH_IMPORT_ERROR = None


logger = logging.getLogger(__name__)


class ResearchGraphState(TypedDict, total=False):
    """LangGraph state for the MechResearch workflow."""

    topic: str
    state: SummaryState
    events: Annotated[list[dict[str, Any]], operator.add]
    evaluation: EvaluationResult | None


def _ensure_langgraph_available() -> None:
    if StateGraph is None or END is None:
        raise ModuleNotFoundError(
            "LangGraph is not installed. Install optional dependencies with "
            "`pip install -r requirements-langgraph.txt` from the backend directory."
        ) from _LANGGRAPH_IMPORT_ERROR


class LangGraphDeepResearchAgent(DeepResearchAgent):
    """DeepResearch agent orchestrated by LangGraph nodes."""

    def __init__(self, config: Configuration | None = None) -> None:
        _ensure_langgraph_available()
        super().__init__(config=config)
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ResearchGraphState)
        builder.add_node("plan", self._plan_node)
        builder.add_node("execute_tasks", self._execute_tasks_node)
        builder.add_node("write_report", self._write_report_node)
        builder.add_node("evaluate", self._evaluate_node)

        builder.set_entry_point("plan")
        builder.add_edge("plan", "execute_tasks")
        builder.add_edge("execute_tasks", "write_report")
        builder.add_edge("write_report", "evaluate")
        builder.add_edge("evaluate", END)
        return builder.compile()

    def _plan_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        topic = graph_state["topic"]
        state = SummaryState(research_topic=topic)
        events: list[dict[str, Any]] = [{"type": "status", "message": "LangGraph: 规划研究任务"}]

        todo_items = self.planner.plan_todo_list(state)
        for event in self._drain_tool_events(state, step=0):
            events.append(event)

        if not todo_items:
            todo_items = [self.planner.create_fallback_task(state)]
            state.todo_items = todo_items

        events.append(
            {
                "type": "todo_list",
                "tasks": [self._serialize_task(task) for task in state.todo_items],
                "step": 0,
            }
        )
        return {"state": state, "events": events}

    def _execute_tasks_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = graph_state["state"]
        events: list[dict[str, Any]] = [{"type": "status", "message": "LangGraph: 执行检索、RAG 与子任务总结"}]

        for step, task in enumerate(state.todo_items, start=1):
            events.append(self._task_status_event(task, "in_progress", step))
            try:
                for event in self._execute_task(state, task, emit_stream=False, step=step):
                    events.append(event)
                events.append(self._task_status_event(task, task.status, step))
            except Exception as exc:  # pragma: no cover - defensive runtime path.
                logger.exception("LangGraph task execution failed: %s", exc)
                task.status = "failed"
                events.append(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "failed",
                        "title": task.title,
                        "intent": task.intent,
                        "detail": str(exc),
                        "step": step,
                    }
                )

        return {"state": state, "events": events}

    def _write_report_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = graph_state["state"]
        events: list[dict[str, Any]] = [{"type": "status", "message": "LangGraph: 汇总生成研究报告"}]

        report = self.reporting.generate_report(state)
        for event in self._drain_tool_events(state, step=len(state.todo_items) + 1):
            events.append(event)

        state.structured_report = report
        state.running_summary = report

        note_event = self._persist_final_report(state, report)
        if note_event:
            events.append(note_event)

        events.append(
            {
                "type": "final_report",
                "report": report,
                "note_id": state.report_note_id,
                "note_path": state.report_note_path,
            }
        )
        return {"state": state, "events": events}

    def _evaluate_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = graph_state["state"]
        events: list[dict[str, Any]] = []
        evaluation: EvaluationResult | None = None

        if self.evaluator and state.structured_report:
            events.append({"type": "status", "message": "LangGraph: 评估报告完整性"})
            evaluation = self.evaluator.evaluate(state.structured_report, state.todo_items)
            events.append(
                {
                    "type": "evaluation",
                    "score": evaluation.score,
                    "has_sources": evaluation.has_sources,
                    "has_tech_stack": evaluation.has_tech_stack,
                    "has_risks": evaluation.has_risks,
                    "has_actionable_steps": evaluation.has_actionable_steps,
                    "suggestions": evaluation.suggestions,
                    "details": evaluation.details,
                }
            )

        events.append({"type": "done"})
        return {"state": state, "evaluation": evaluation, "events": events}

    def run(self, topic: str) -> SummaryStateOutput:
        """Execute the LangGraph workflow and return the same output model."""

        final_state: ResearchGraphState = self._graph.invoke({"topic": topic, "events": []})
        state = final_state["state"]
        return SummaryStateOutput(
            running_summary=state.running_summary,
            report_markdown=state.structured_report,
            todo_items=state.todo_items,
            evaluation=final_state.get("evaluation"),
        )

    def run_stream(self, topic: str) -> Iterator[dict[str, Any]]:
        """Yield frontend-compatible high-level events from LangGraph snapshots."""

        seen_events = 0
        for snapshot in self._graph.stream({"topic": topic, "events": []}, stream_mode="values"):
            events = snapshot.get("events", [])
            for event in events[seen_events:]:
                yield event
            seen_events = len(events)

    def _task_status_event(self, task: TodoItem, status: str, step: int) -> dict[str, Any]:
        return {
            "type": "task_status",
            "task_id": task.id,
            "status": status,
            "title": task.title,
            "intent": task.intent,
            "summary": task.summary,
            "sources_summary": task.sources_summary,
            "note_id": task.note_id,
            "note_path": task.note_path,
            "step": step,
        }


def run_deep_research_langgraph(topic: str, config: Configuration | None = None) -> SummaryStateOutput:
    """Convenience function mirroring the original `run_deep_research` API."""

    agent = LangGraphDeepResearchAgent(config=config)
    return agent.run(topic)

