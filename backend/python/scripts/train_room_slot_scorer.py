"""Train CatBoost room+slot scorer for V3.5 placement recommendation.

Contract:
  input  = teaching task features + one candidate room + one candidate slot
  output = score for ranking candidate room+slot pairs
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "backend" / "data" / "parsed" / "room_slot_training_dataset"
DEFAULT_TRAIN_PATH = DEFAULT_DATA_DIR / "train.csv"
DEFAULT_VALID_PATH = DEFAULT_DATA_DIR / "valid.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "models" / "v3.5" / "room_slot_scorer"
MODEL_FILENAME = "room_slot_catboost.cbm"
META_FILENAME = "room_slot_scorer_meta.json"
REPORT_FILENAME = "evaluation_report.json"

EXCLUDED_FEATURES = {"label", "split", "source_schedule"}
CATEGORICAL_FEATURES = [
    "source_semester",
    "course_id",
    "course_code",
    "course_code_prefix",
    "course_name",
    "course_type",
    "required_room_type",
    "teacher_name",
    "class_name",
    "class_names",
    "major",
    "department",
    "grade",
    "class_index",
    "is_zhuanshengben",
    "academic_year",
    "semester",
    "candidate_room",
    "candidate_room_type",
    "candidate_slot_key",
    "room_type_match",
]
NUMERIC_FEATURES = [
    "total_hours",
    "segment_count",
    "teacher_count",
    "class_count",
    "candidate_capacity",
    "candidate_day_of_week",
    "candidate_period_index",
]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TASK_GROUP_FIELDS = ["source_schedule", "course_id", "class_name"]
TOP_KS = [1, 5, 10, 20]


def train_room_slot_scorer(
    *,
    train_path: Path = DEFAULT_TRAIN_PATH,
    valid_path: Path = DEFAULT_VALID_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    iterations: int = 300,
    learning_rate: float = 0.08,
    depth: int = 8,
    random_seed: int = 20260615,
    examples: int = 20,
) -> dict[str, Any]:
    catboost = _load_catboost()
    CatBoostClassifier = catboost.CatBoostClassifier
    Pool = catboost.Pool

    train_df = _load_frame(train_path)
    valid_df = _load_frame(valid_path)
    _assert_columns(train_df, train_path)
    _assert_columns(valid_df, valid_path)

    train_x = train_df[FEATURES]
    train_y = train_df["label"].astype(int)
    valid_x = valid_df[FEATURES]
    valid_y = valid_df["label"].astype(int)

    train_pool = Pool(train_x, label=train_y, cat_features=CATEGORICAL_FEATURES)
    valid_pool = Pool(valid_x, label=valid_y, cat_features=CATEGORICAL_FEATURES)
    model = CatBoostClassifier(
        iterations=iterations,
        learning_rate=learning_rate,
        depth=depth,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=random_seed,
        verbose=50,
        allow_writing_files=False,
    )
    model.fit(train_pool, eval_set=valid_pool, use_best_model=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / MODEL_FILENAME
    meta_path = output_dir / META_FILENAME
    report_path = output_dir / REPORT_FILENAME
    model.save_model(str(model_path))

    valid_scores = model.predict_proba(valid_pool)[:, 1]
    evaluation = _evaluate_topk(valid_df, valid_scores, examples=examples)
    feature_importance = _feature_importance(model, train_pool)
    meta = {
        "model_type": "catboost_room_slot_binary_scorer",
        "version": "v1",
        "model_path": str(model_path),
        "train_path": str(train_path),
        "valid_path": str(valid_path),
        "features": FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "excluded_features": sorted(EXCLUDED_FEATURES),
        "task_group_fields": TASK_GROUP_FIELDS,
        "params": {
            "iterations": iterations,
            "learning_rate": learning_rate,
            "depth": depth,
            "loss_function": "Logloss",
            "eval_metric": "AUC",
            "random_seed": random_seed,
        },
        "row_counts": {
            "train": int(len(train_df)),
            "valid": int(len(valid_df)),
        },
        "label_counts": {
            "train": _label_counts(train_df),
            "valid": _label_counts(valid_df),
        },
        "best_iteration": int(model.get_best_iteration() or 0),
        "best_score": model.get_best_score(),
        "feature_importance": feature_importance,
    }
    report = {
        "status": "ok",
        "model_path": str(model_path),
        "meta_path": str(meta_path),
        "features": FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "metrics": evaluation["metrics"],
        "label_counts": meta["label_counts"],
        "examples": evaluation["examples"],
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "model_path": str(model_path),
        "meta_path": str(meta_path),
        "report_path": str(report_path),
        "metrics": evaluation["metrics"],
        "row_counts": meta["row_counts"],
        "label_counts": meta["label_counts"],
    }


def _load_catboost():
    try:
        import catboost
    except ModuleNotFoundError as exc:
        raise SystemExit("catboost is not installed. Run the backend Python dependency install first.") from exc
    return catboost


def _load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"training file not found: {path}")
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip() for column in frame.columns]
    for column in CATEGORICAL_FEATURES + TASK_GROUP_FIELDS:
        frame[column] = frame.get(column, "").fillna("").astype(str).str.strip()
    for column in NUMERIC_FEATURES:
        frame[column] = pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0)
    frame["label"] = pd.to_numeric(frame.get("label", 0), errors="coerce").fillna(0).astype(int)
    return frame


def _assert_columns(frame: pd.DataFrame, path: Path) -> None:
    required = set(FEATURES) | {"label"} | set(TASK_GROUP_FIELDS)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SystemExit(f"{path} missing required columns: {missing}")


def _evaluate_topk(valid_df: pd.DataFrame, scores: Any, *, examples: int) -> dict[str, Any]:
    scored = valid_df.copy()
    scored["_score"] = scores
    grouped = scored.groupby(TASK_GROUP_FIELDS, sort=False, dropna=False)
    task_count = 0
    hit_counts = Counter()
    reciprocal_rank_sum = 0.0
    positive_candidate_count = 0
    examples_out: list[dict[str, Any]] = []

    for key, group in grouped:
        task_count += 1
        ranked = group.sort_values("_score", ascending=False).reset_index(drop=True)
        positive_ranks = [index + 1 for index, label in enumerate(ranked["label"].astype(int).tolist()) if label == 1]
        if not positive_ranks:
            continue
        positive_candidate_count += len(positive_ranks)
        first_rank = min(positive_ranks)
        reciprocal_rank_sum += 1.0 / first_rank
        for top_k in TOP_KS:
            if first_rank <= top_k:
                hit_counts[top_k] += 1
        if len(examples_out) < examples:
            examples_out.append(_example_row(key, ranked, first_rank))

    metrics: dict[str, Any] = {
        "task_count": task_count,
        "positive_candidate_count": positive_candidate_count,
        "mrr": round(reciprocal_rank_sum / task_count, 6) if task_count else 0.0,
    }
    for top_k in TOP_KS:
        metrics[f"top{top_k}_hit_rate"] = round(hit_counts[top_k] / task_count, 6) if task_count else 0.0
    return {"metrics": metrics, "examples": examples_out}


def _example_row(key: Any, ranked: pd.DataFrame, first_rank: int) -> dict[str, Any]:
    key_values = key if isinstance(key, tuple) else (key,)
    first = ranked.iloc[0]
    positives = ranked[ranked["label"].astype(int) == 1].head(5)
    return {
        "task": {
            "source_schedule": key_values[0] if len(key_values) > 0 else "",
            "course_id": key_values[1] if len(key_values) > 1 else "",
            "class_name": key_values[2] if len(key_values) > 2 else "",
            "course_name": str(first.get("course_name", "")),
            "teacher_name": str(first.get("teacher_name", "")),
        },
        "first_positive_rank": int(first_rank),
        "top_candidates": [_candidate_dict(row) for _, row in ranked.head(10).iterrows()],
        "positive_candidates_preview": [_candidate_dict(row) for _, row in positives.iterrows()],
    }


def _candidate_dict(row: pd.Series) -> dict[str, Any]:
    return {
        "room": str(row.get("candidate_room", "")),
        "room_type": str(row.get("candidate_room_type", "")),
        "day_of_week": int(row.get("candidate_day_of_week", 0)),
        "period_index": int(row.get("candidate_period_index", 0)),
        "score": round(float(row.get("_score", 0.0)), 8),
        "label": int(row.get("label", 0)),
        "room_type_match": str(row.get("room_type_match", "")),
    }


def _feature_importance(model: Any, train_pool: Any) -> list[dict[str, Any]]:
    values = model.get_feature_importance(train_pool)
    rows = [
        {"feature": feature, "importance": round(float(importance), 8)}
        for feature, importance in zip(FEATURES, values, strict=False)
    ]
    return sorted(rows, key=lambda row: row["importance"], reverse=True)


def _label_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {str(key): int(value) for key, value in frame["label"].value_counts().sort_index().items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train CatBoost room+slot scorer.")
    parser.add_argument("--train", default=str(DEFAULT_TRAIN_PATH))
    parser.add_argument("--valid", default=str(DEFAULT_VALID_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--random-seed", type=int, default=20260615)
    parser.add_argument("--examples", type=int, default=20)
    args = parser.parse_args()
    result = train_room_slot_scorer(
        train_path=Path(args.train),
        valid_path=Path(args.valid),
        output_dir=Path(args.output_dir),
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        depth=args.depth,
        random_seed=args.random_seed,
        examples=args.examples,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
