"""LLM client for reconcile — conflict analysis and content synthesis via Ollama."""

import logging

import httpx

log = logging.getLogger("synapse.llm")

CONFLICT_PROMPT = """Analyze these two knowledge documents and determine if they conflict.

Document A:
Title: {title_a}
Content: {content_a}

Document B:
Title: {title_b}
Content: {content_b}

Respond in this exact JSON format:
{{
  "is_conflict": true/false,
  "conflict_type": "contradiction|overlap|outdated|none",
  "reason": "brief explanation of the conflict or why no conflict exists",
  "supersede_id": "a_or_b_or_none",
  "merged_content": "if conflict, provide merged/resolved content. if no conflict, empty string"
}}

Be conservative: only mark as conflict if the documents genuinely contradict each other.
Overlapping information is not a conflict unless one document contradicts the other."""

# Judge chain: gemma4 first (fastest + cleanest fenced JSON, tested 3/10/26),
# glm-flash second (deeper Thai analysis — catches pairs gemma4 misses),
# qwen3:8b last (local offline fallback). Kept explicit (not from env) so a
# missing model is a config bug we notice in llm_errors, not a silent zero.
JUDGE_MODEL_CHAIN = ["gemma4:cloud", "glm-5.3-flash:cloud", "qwen3:8b"]


async def analyze_conflict(
    doc_a: dict,
    doc_b: dict,
    settings,
) -> dict | None:
    """Use a local Ollama LLM to analyze whether two documents conflict.

    Tries each model in JUDGE_MODEL_CHAIN until one answers. Returns dict with:
    is_conflict, conflict_type, reason, supersede_id, merged_content.
    Returns None if every model failed (caller must surface this as llm_errors).
    """
    import json

    prompt = CONFLICT_PROMPT.format(
        title_a=doc_a.get("title", ""),
        content_a=doc_a.get("content", "")[:2000],
        title_b=doc_b.get("title", ""),
        content_b=doc_b.get("content", "")[:2000],
    )

    last_error = None
    for judge_model in JUDGE_MODEL_CHAIN:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={
                        "model": judge_model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "think": False,  # skip CoT: 43s -> ~8s per pair
                    },
                )

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code} from {judge_model}"
                log.warning("LLM request failed (%s): %s", judge_model, response.status_code)
                continue

            data = response.json()
            text = data.get("response", "").strip()

            # Try to parse JSON from the response
            # LLM may wrap JSON in markdown code blocks or lead with prose
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                # Some cloud models answer with analysis prose then a bare
                # JSON object at the end — extract the outermost braces.
                if "{" in text and "}" in text:
                    candidate = text[text.index("{"):text.rindex("}") + 1]
                    result = json.loads(candidate)

            if result is None:
                raise json.JSONDecodeError("no JSON found in response", text, 0)

            # Normalize boolean
            if isinstance(result.get("is_conflict"), str):
                result["is_conflict"] = result["is_conflict"].lower() in ("true", "yes")

            return result

        except json.JSONDecodeError as e:
            last_error = f"bad JSON from {judge_model}: {e}"
            log.warning("Failed to parse LLM response as JSON (%s): %s", judge_model, e)
        except Exception as e:
            last_error = f"request to {judge_model} failed: {e}"
            log.warning("LLM conflict analysis failed (%s): %s", judge_model, e)

    log.error("All judge models failed: %s", last_error)
    return None


async def summarize_content(
    content: str,
    title: str,
    settings,
    judge_model: str = "qwen3:8b",
) -> str | None:
    """Use LLM to summarize content. Returns summary or None."""
    prompt = (
        f"Summarize the following document concisely, preserving key information. "
        f"Keep the summary under 500 words.\n\n"
        f"Title: {title}\n\n"
        f"Content:\n{content[:8000]}"
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": judge_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("response", "").strip()
    except Exception as e:
        log.warning("LLM summarization failed: %s", e)

    return None