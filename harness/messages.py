"""Builders for every hop message; each result must satisfy its wires/*.yaml contract."""


def intake_to_research(brief):
    return {"topic": brief["topic"], "focus_areas": brief.get("key_points") or []}


def intake_to_draft(brief, dossier):
    message = {"brief": brief}
    if dossier is not None:
        message["dossier"] = dossier
    return message


def draft_to_review(brief, draft, round_num, check_results):
    return {"draft": draft, "brief": brief, "revision_round": round_num, "deterministic_checks": check_results}


def review_to_draft(brief, draft, issues, round_num):
    return {
        "draft_title": draft["title"],
        "issues": issues,
        "revision_round": round_num,
        "brief": brief,
        "previous_draft": draft,
    }


def review_to_dispatch(draft, review, revision_rounds, dossier=None):
    message = {
        "draft": draft,
        "review_summary": {
            "score": review["score"],
            "dimension_scores": review.get("dimension_scores", {}),
            "revision_rounds": revision_rounds,
            "review_status": "approved",
        },
    }
    sources = [s for s in (dossier or {}).get("sources", []) if s.get("url")]
    if sources:
        message["sources"] = sources
    return message
