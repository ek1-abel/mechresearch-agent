"""Report quality evaluation service."""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents import HelloAgentsLLM

from models import EvaluationResult, TodoItem
from prompts import report_evaluator_instructions

logger = logging.getLogger(__name__)


class EvaluatorService:
    """Evaluates generated research reports for quality and completeness."""

    def __init__(self, llm: HelloAgentsLLM):
        self.llm = llm

    def evaluate(
        self, report: str, todo_items: list[TodoItem]
    ) -> EvaluationResult:
        """Run structured evaluation of a research report."""

        task_summary = "\n".join(
            f"- 任务 {t.id}: {t.title} (状态: {t.status})"
            for t in todo_items
        )

        messages = [
            {"role": "system", "content": report_evaluator_instructions},
            {
                "role": "user",
                "content": (
                    f"请评估以下研究报告：\n\n"
                    f"## 任务列表\n{task_summary}\n\n"
                    f"## 报告内容\n{report}"
                ),
            },
        ]

        try:
            response = self.llm.invoke(messages)
            return self._parse_evaluation(response)
        except Exception as exc:
            logger.exception("Report evaluation failed: %s", exc)
            return EvaluationResult(
                score=0,
                details=f"评估过程出错: {exc}",
                suggestions=["评估失败，请检查 LLM 连接"],
            )

    def _parse_evaluation(self, response: str) -> EvaluationResult:
        """Parse the LLM JSON response into an EvaluationResult."""
        text = response.strip()

        if "```json" in text:
            text = text.split("```json", 1)[1]
            text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            text = text.split("```", 1)[0]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        try:
            data: dict[str, Any] = json.loads(text)
            return EvaluationResult(
                score=float(data.get("score", 0)),
                has_sources=bool(data.get("has_sources", False)),
                has_tech_stack=bool(data.get("has_tech_stack", False)),
                has_risks=bool(data.get("has_risks", False)),
                has_actionable_steps=bool(data.get("has_actionable_steps", False)),
                suggestions=list(data.get("suggestions", [])),
                details=str(data.get("details", "")),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse evaluation JSON: %s", exc)
            return EvaluationResult(
                score=0,
                details=f"评估结果解析失败: {response[:200]}",
                suggestions=["LLM 返回格式异常，请重试"],
            )
