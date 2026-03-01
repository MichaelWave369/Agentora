from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from app.models import Capsule, MemoryUsefulnessMetric


def update_usefulness(
    session: Session,
    run_id: int,
    retrieved_capsule_ids: list[int],
    used_capsule_ids: list[int],
    helped_final_answer: bool = False,
    helped_tool_execution: bool = False,
) -> list[MemoryUsefulnessMetric]:
    used = set(used_capsule_ids)
    out: list[MemoryUsefulnessMetric] = []
    for cid in retrieved_capsule_ids:
        cap = session.get(Capsule, cid)
        if not cap:
            continue
        metric = session.exec(select(MemoryUsefulnessMetric).where(MemoryUsefulnessMetric.capsule_id == cid)).first()
        if not metric:
            metric = MemoryUsefulnessMetric(capsule_id=cid)
        metric.retrieved_count += 1
        if cid in used:
            metric.retrieved_and_used_count += 1
            cap.success_count += 1
            cap.helped_final_answer_score = min(1.0, cap.helped_final_answer_score + (0.1 if helped_final_answer else 0.03))
            metric.helped_tool_execution_score = min(1.0, metric.helped_tool_execution_score + (0.08 if helped_tool_execution else 0.0))
        else:
            metric.retrieved_but_unused_count += 1
            cap.failure_count += 1
            metric.stale_penalty = min(1.0, metric.stale_penalty + 0.03)
        metric.helped_final_answer_score = min(1.0, metric.helped_final_answer_score + (0.1 if helped_final_answer and cid in used else 0.0))
        metric.contradiction_penalty = min(1.0, metric.contradiction_penalty + (0.08 if cap.contradiction_flag else 0.0))
        metric.confidence_gain = max(-1.0, min(1.0, metric.helped_final_answer_score - metric.contradiction_penalty - metric.stale_penalty))
        metric.updated_at = datetime.utcnow()

        cap.consolidation_score = max(0.0, min(1.0, cap.consolidation_score + metric.confidence_gain * 0.04))
        cap.trust_score = max(0.0, min(1.0, cap.trust_score + (0.02 if cid in used else -0.01)))
        cap.last_used_at = datetime.utcnow()
        session.add(cap)
        session.add(metric)
        out.append(metric)
    session.commit()
    return out
